"""Tests for the retry / idempotency store API on ``PgBacktestJobStore``.

These tests use lightweight in-memory fakes to validate the SQL
contract without requiring a real PostgreSQL connection. They focus
on:

* ``claim_next_queued`` filtering by ``next_retry_at``
* ``mark_retry`` rewinding state to ``queued`` with bumped ``attempt``
* ``get_by_idempotency_key`` JSONB lookup with user-scope isolation
* ``create_job`` persisting ``max_attempts``
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

import pytest

from getrich_backtest import PgBacktestJobStore


# ---------------------------------------------------------------- fakes


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


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------- create_job


def test_create_job_persists_max_attempts() -> None:
    cursor = _FakeCursor()
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    _run(
        store.create_job(
            "backtest",
            "ref-1",
            request_json={"_test_marker": "retry"},
            max_attempts=5,
            conn=conn,
        )
    )

    sql, params = cursor.statements[0]
    assert "INSERT INTO backtest_jobs" in sql
    assert "max_attempts" in sql
    # ``max_attempts`` is bound by name in the INSERT.
    assert params["max_attempts"] == 5
    # ``attempt`` and ``next_retry_at`` are NOT bound — they fall back
    # to the SQL DEFAULT (1 / NULL). Verifying they're absent guards
    # against accidental over-binding.
    assert "attempt" not in params
    assert "next_retry_at" not in params


def test_create_job_default_max_attempts_is_one() -> None:
    cursor = _FakeCursor()
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    _run(store.create_job("backtest", "ref-x", request_json={}, conn=conn))

    sql, params = cursor.statements[0]
    assert params["max_attempts"] == 1


def test_create_job_rejects_max_attempts_zero() -> None:
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="max_attempts"):
        _run(store.create_job("backtest", "ref-1", request_json={}, max_attempts=0))


# ---------------------------------------------------------------- claim_next_queued


def test_claim_next_queued_filter_includes_next_retry_at() -> None:
    cursor = _FakeCursor(fetchone=None)
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    _run(store.claim_next_queued("backtest", conn=conn))

    sql = cursor.statements[0][0]
    # The retry column is part of the WHERE filter.
    assert "next_retry_at" in sql
    assert "next_retry_at IS NULL" in sql
    assert "next_retry_at <= NOW()" in sql
    # Index hint — partial index on queued rows orders by next_retry_at.
    assert "next_retry_at NULLS FIRST" in sql
    # P2 #311: the CTE also includes the stuck-running recovery branch.
    assert "WITH candidate AS" in sql
    assert "status = 'running'" in sql
    assert "updated_at < NOW() - (%(stale_seconds)s || ' seconds')::interval" in sql


def test_claim_next_queued_returns_retry_fields() -> None:
    job_row = {
        "job_id": "abc",
        "job_type": "backtest",
        "ref_id": "run-1",
        "status": "running",
        "request_json": "{}",
        "progress": 0,
        "error_message": "previous error",
        "attempt": 3,
        "max_attempts": 5,
        "next_retry_at": None,
        "created_at": datetime(2026, 6, 2, 9, 30),
        "started_at": datetime(2026, 6, 2, 9, 30),
        "completed_at": None,
        "updated_at": datetime(2026, 6, 2, 9, 30),
    }
    cursor = _FakeCursor(fetchone=job_row)
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    claimed = _run(store.claim_next_queued("backtest", conn=conn))

    assert claimed is not None
    assert claimed["job_id"] == "abc"
    assert claimed["attempt"] == 3
    assert claimed["max_attempts"] == 5
    # next_retry_at stays None for the first iteration.
    assert claimed["next_retry_at"] is None


# ---------------------------------------------------------------- mark_retry


def test_mark_retry_writes_retry_state_sql() -> None:
    cursor = _FakeCursor()
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    next_at = datetime(2026, 6, 2, 10, 0, 0)
    _run(
        store.mark_retry(
            "job-1",
            error_message="flaky",
            next_retry_at=next_at,
            conn=conn,
        )
    )

    sql, params = cursor.statements[0]
    assert "status = 'queued'" in sql
    assert "progress = 0" in sql
    assert "attempt = attempt + 1" in sql
    assert "next_retry_at = %(next_retry_at)s" in sql
    assert "error_message = %(error_message)s" in sql
    assert "started_at = NULL" in sql
    assert "completed_at = NULL" in sql
    assert params["job_id"] == "job-1"
    assert params["error_message"] == "flaky"
    assert params["next_retry_at"] == next_at


def test_mark_retry_returns_true_on_success() -> None:
    cursor = _FakeCursor()
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    result = _run(
        store.mark_retry(
            "job-1",
            error_message="boom",
            next_retry_at=datetime(2026, 6, 2, 10, 0, 0),
            conn=conn,
        )
    )
    assert result is True


# ---------------------------------------------------------------- idempotency lookup


def test_get_by_idempotency_key_uses_jsonb_lookup() -> None:
    job_row = {
        "job_id": "abc",
        "job_type": "backtest",
        "ref_id": "run-1",
        "user_id": None,
        "status": "queued",
        "request_json": json.dumps({"_idempotency_key": "shared-key"}),
        "progress": 0,
        "error_message": None,
        "attempt": 1,
        "max_attempts": 1,
        "next_retry_at": None,
        "created_at": datetime(2026, 6, 2, 9, 30),
        "started_at": None,
        "completed_at": None,
        "updated_at": datetime(2026, 6, 2, 9, 30),
    }
    cursor = _FakeCursor(fetchone=job_row)
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    row = _run(store.get_by_idempotency_key(key="shared-key", user_id=None, conn=conn))

    assert row is not None
    assert row["job_id"] == "abc"
    sql, params = cursor.statements[0]
    # Idempotency key is still looked up in the JSONB payload; owner
    # filtering is now via the ``user_id`` column, not JSONB.
    assert "request_json->>'_idempotency_key'" in sql
    assert "user_id IS NOT DISTINCT FROM %(user_id)s" in sql
    # Parameter names are ``key`` and ``user_id`` (not the JSONB column names).
    assert params["key"] == "shared-key"
    assert params["user_id"] is None


def test_get_by_idempotency_key_scopes_by_user_id() -> None:
    cursor = _FakeCursor(fetchone=None)
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    _run(store.get_by_idempotency_key(key="k", user_id="alice", conn=conn))

    sql, params = cursor.statements[0]
    # User-scoped branch: ``user_id IS NOT DISTINCT FROM %(user_id)s``
    assert "user_id IS NOT DISTINCT FROM %(user_id)s" in sql
    assert params["user_id"] == "alice"
    assert params["key"] == "k"


def test_get_by_idempotency_key_returns_none_when_missing() -> None:
    cursor = _FakeCursor(fetchone=None)
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    row = _run(store.get_by_idempotency_key(key="never-used", user_id=None, conn=conn))
    assert row is None
