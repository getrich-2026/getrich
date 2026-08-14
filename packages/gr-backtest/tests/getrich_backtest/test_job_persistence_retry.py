"""Tests for per-job retry override fields on PgBacktestJobStore.

P1 #6: ``retry_base_seconds`` / ``retry_cap_seconds`` / ``retry_jitter_pct``
become optional parameters on ``create_job`` and are returned by the
``SELECT`` / ``CLAIM`` / ``idempotency-key lookup`` paths.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import pytest

from getrich_backtest import PgBacktestJobStore


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _FakeCursor:
    def __init__(
        self,
        *,
        fetchone: dict[str, Any] | None = None,
        fetchall: list[dict[str, Any]] | None = None,
        rowcount: int = 1,
    ) -> None:
        self.statements: list[tuple[str, dict[str, Any] | None]] = []
        self._fetchone = fetchone
        self._fetchall = fetchall or []
        self.rowcount = rowcount

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, sql: str, params: dict[str, Any] | None = None) -> None:
        self.statements.append((sql, params))

    async def fetchone(self) -> dict[str, Any] | None:
        return self._fetchone

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._fetchall


class _FakeConn:
    def __init__(self, cursor: _FakeCursor | None = None) -> None:
        self.cursor_obj = cursor or _FakeCursor()
        self.commits = 0

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj

    async def commit(self) -> None:
        self.commits += 1


class _PoolConnCtx:
    def __init__(self, conn: _FakeConn) -> None:
        self.conn = conn

    async def __aenter__(self) -> _FakeConn:
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return None


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self.conn = conn

    def connection(self) -> _PoolConnCtx:
        return _PoolConnCtx(self.conn)


# ---------------------------------------------------------------- create_job writes retry_*


def test_create_job_writes_retry_overrides_when_provided() -> None:
    cursor = _FakeCursor()
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(conn))  # type: ignore[arg-type]

    _run(
        store.create_job(
            "backtest",
            "run-1",
            request_json={"x": 1},
            retry_base_seconds=2.5,
            retry_cap_seconds=30.0,
            retry_jitter_pct=0.15,
        )
    )

    sql, params = cursor.statements[0]
    assert "INSERT INTO backtest_jobs" in sql
    # INSERT column list must include the new fields.
    assert "retry_base_seconds" in sql
    assert "retry_cap_seconds" in sql
    assert "retry_jitter_pct" in sql
    # Values are passed through verbatim.
    assert params["retry_base_seconds"] == 2.5
    assert params["retry_cap_seconds"] == 30.0
    assert params["retry_jitter_pct"] == 0.15


def test_create_job_passes_null_when_retry_overrides_omitted() -> None:
    cursor = _FakeCursor()
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(conn))  # type: ignore[arg-type]

    _run(store.create_job("backtest", "run-1"))

    sql, params = cursor.statements[0]
    assert params["retry_base_seconds"] is None
    assert params["retry_cap_seconds"] is None
    assert params["retry_jitter_pct"] is None


# ---------------------------------------------------------------- create_job input validation


def test_create_job_rejects_negative_retry_base() -> None:
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="retry_base_seconds must be non-negative"):
        _run(store.create_job("backtest", "run-1", retry_base_seconds=-0.1))


def test_create_job_rejects_cap_less_than_base() -> None:
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="retry_cap_seconds must be >= retry_base_seconds"):
        _run(
            store.create_job(
                "backtest",
                "run-1",
                retry_base_seconds=5.0,
                retry_cap_seconds=2.0,
            )
        )


# ---------------------------------------------------------------- SELECT paths return retry_*


def test_claim_next_queued_returns_retry_overrides() -> None:
    """The claimed row dictionary must carry the per-job retry columns."""
    job_row = {
        "job_id": "abc",
        "job_type": "backtest",
        "ref_id": "run-1",
        "status": "queued",
        "request_json": "{}",
        "progress": 0,
        "error_message": None,
        "attempt": 1,
        "max_attempts": 3,
        "next_retry_at": None,
        "retry_base_seconds": 2.5,
        "retry_cap_seconds": 30.0,
        "retry_jitter_pct": 0.15,
        "created_at": datetime(2026, 6, 2, 9, 30),
        "started_at": None,
        "completed_at": None,
        "updated_at": datetime(2026, 6, 2, 9, 30),
    }
    cursor = _FakeCursor(fetchone=job_row)
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    claimed = _run(store.claim_next_queued("backtest", conn=conn))

    assert claimed is not None
    assert claimed["retry_base_seconds"] == 2.5
    assert claimed["retry_cap_seconds"] == 30.0
    assert claimed["retry_jitter_pct"] == 0.15
    # The claim SELECT must include the new columns.
    assert "retry_base_seconds" in cursor.statements[0][0]
    assert "retry_cap_seconds" in cursor.statements[0][0]
    assert "retry_jitter_pct" in cursor.statements[0][0]


def test_claim_next_queued_returns_null_retry_overrides_for_legacy_rows() -> None:
    """Legacy rows (created before migration 022) have NULL retry_* columns;
    the runner must see them as None and fall back to its defaults."""
    job_row = {
        "job_id": "abc",
        "job_type": "backtest",
        "ref_id": "run-1",
        "status": "queued",
        "request_json": "{}",
        "progress": 0,
        "error_message": None,
        "attempt": 1,
        "max_attempts": 3,
        "next_retry_at": None,
        "retry_base_seconds": None,
        "retry_cap_seconds": None,
        "retry_jitter_pct": None,
        "created_at": datetime(2026, 6, 2, 9, 30),
        "started_at": None,
        "completed_at": None,
        "updated_at": datetime(2026, 6, 2, 9, 30),
    }
    cursor = _FakeCursor(fetchone=job_row)
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    claimed = _run(store.claim_next_queued("backtest", conn=conn))

    assert claimed is not None
    assert claimed["retry_base_seconds"] is None
    assert claimed["retry_cap_seconds"] is None
    assert claimed["retry_jitter_pct"] is None


# ---------------------------------------------------------------- request_hash (migration 023)


def test_create_job_writes_request_hash_when_provided() -> None:
    """When ``request_hash`` is supplied, the INSERT must include the
    column and bind the value verbatim."""
    cursor = _FakeCursor()
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(conn))  # type: ignore[arg-type]

    h = "1" * 64
    _run(
        store.create_job(
            "backtest",
            "run-1",
            request_json={"x": 1},
            request_hash=h,
        )
    )

    sql, params = cursor.statements[0]
    assert "INSERT INTO backtest_jobs" in sql
    assert "request_hash" in sql
    assert params["request_hash"] == h


def test_create_job_passes_null_request_hash_when_omitted() -> None:
    cursor = _FakeCursor()
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(conn))  # type: ignore[arg-type]

    _run(store.create_job("backtest", "run-1"))

    sql, params = cursor.statements[0]
    assert params["request_hash"] is None


def test_create_job_rejects_non_64_char_request_hash() -> None:
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="64-char sha256 hex string"):
        _run(store.create_job("backtest", "run-1", request_hash="tooshort"))
    with pytest.raises(ValueError, match="64-char sha256 hex string"):
        _run(store.create_job("backtest", "run-1", request_hash="z" * 64))  # non-hex characters


def test_get_by_idempotency_key_returns_request_hash() -> None:
    """The SELECT must include ``request_hash`` so the service can compare."""
    h = "2" * 64
    job_row = {
        "job_id": "abc",
        "job_type": "backtest",
        "ref_id": "run-1",
        "status": "queued",
        "request_json": "{}",
        "request_hash": h,
        "progress": 0,
        "error_message": None,
        "attempt": 1,
        "max_attempts": 3,
        "next_retry_at": None,
        "retry_base_seconds": None,
        "retry_cap_seconds": None,
        "retry_jitter_pct": None,
        "created_at": datetime(2026, 6, 2, 9, 30),
        "started_at": None,
        "completed_at": None,
        "updated_at": datetime(2026, 6, 2, 9, 30),
    }
    cursor = _FakeCursor(fetchone=job_row)
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    claimed = _run(store.get_by_idempotency_key(key="abc-123", conn=conn))

    assert claimed is not None
    assert claimed["request_hash"] == h
    assert "request_hash" in cursor.statements[0][0]


def test_get_by_idempotency_key_legacy_row_returns_null_hash() -> None:
    """Legacy rows (predating migration 023) have ``request_hash = None``;
    the SELECT must return it verbatim so the service can fall back to
    permissive-match semantics."""
    job_row = {
        "job_id": "abc",
        "job_type": "backtest",
        "ref_id": "run-1",
        "status": "queued",
        "request_json": "{}",
        "request_hash": None,
        "progress": 0,
        "error_message": None,
        "attempt": 1,
        "max_attempts": 3,
        "next_retry_at": None,
        "retry_base_seconds": None,
        "retry_cap_seconds": None,
        "retry_jitter_pct": None,
        "created_at": datetime(2026, 6, 2, 9, 30),
        "started_at": None,
        "completed_at": None,
        "updated_at": datetime(2026, 6, 2, 9, 30),
    }
    cursor = _FakeCursor(fetchone=job_row)
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    claimed = _run(store.get_by_idempotency_key(key="legacy", conn=conn))

    assert claimed is not None
    assert claimed["request_hash"] is None
