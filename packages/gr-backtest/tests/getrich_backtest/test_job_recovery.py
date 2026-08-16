"""Tests for the stuck-running recovery branch in ``claim_next_queued``.

These tests use lightweight in-memory fakes to validate the SQL contract
for the P2 #311 recovery path without requiring a real PostgreSQL
connection. The recovery branch re-claims ``running`` rows whose
``updated_at`` is older than ``stale_seconds`` ago — a worker that
crashed mid-job.

The same pattern as ``test_job_retry.py`` is reused: inline fakes
defined here so we can iterate independently of other test modules.
"""

from __future__ import annotations

import asyncio
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


# ---------------------------------------------------------------- claim SQL


def test_claim_uses_cte_with_recovery_branch() -> None:
    cursor = _FakeCursor(fetchone=None)
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    _run(store.claim_next_queued("backtest", conn=conn))

    sql = cursor.statements[0][0]
    # The CTE shape and the recovery branch must be present.
    assert "WITH candidate AS" in sql
    assert "status = 'queued'" in sql
    assert "status = 'running'" in sql
    # The recovery scan uses a parameterised threshold.
    assert "updated_at < NOW() - (%(stale_seconds)s || ' seconds')::interval" in sql
    # The FOR UPDATE clause still lives inside the CTE for atomic locking.
    assert "FOR UPDATE SKIP LOCKED" in sql
    # Queued candidates are prioritised over stuck-running.
    assert "CASE WHEN status = 'queued' THEN 0 ELSE 1 END ASC" in sql


def test_claim_passes_stale_seconds_to_sql() -> None:
    cursor = _FakeCursor(fetchone=None)
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    _run(store.claim_next_queued("backtest", stale_seconds=120, conn=conn))

    sql, params = cursor.statements[0]
    assert params["stale_seconds"] == 120
    assert params["job_type"] == "backtest"


def test_claim_default_stale_seconds_is_300() -> None:
    cursor = _FakeCursor(fetchone=None)
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    _run(store.claim_next_queued("backtest", conn=conn))

    sql, params = cursor.statements[0]
    assert params["stale_seconds"] == 300


def test_claim_rejects_negative_stale_seconds() -> None:
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="stale_seconds"):
        _run(store.claim_next_queued("backtest", stale_seconds=-1))


# ---------------------------------------------------------------- _was_recovered flag


def test_claim_returns_was_recovered_false_for_queued_row() -> None:
    job_row = {
        "job_id": "abc",
        "job_type": "backtest",
        "ref_id": "run-1",
        "status": "queued",
        "request_json": "{}",
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

    claimed = _run(store.claim_next_queued("backtest", conn=conn))

    assert claimed is not None
    assert claimed["_was_recovered"] is False
    # Status is forced to running even though the row came back as queued.
    assert claimed["status"] == "running"


def test_claim_returns_was_recovered_true_for_running_row() -> None:
    """A row whose CTE-fetched status is 'running' (recovery) gets the flag."""
    job_row = {
        "job_id": "stuck-1",
        "job_type": "backtest",
        "ref_id": "run-stuck",
        "status": "running",
        "request_json": "{}",
        "progress": 42,
        "error_message": None,
        "attempt": 2,
        "max_attempts": 3,
        "next_retry_at": None,
        "created_at": datetime(2026, 6, 2, 9, 0),
        "started_at": datetime(2026, 6, 2, 9, 1),
        "completed_at": None,
        "updated_at": datetime(2026, 6, 2, 9, 1),
    }
    cursor = _FakeCursor(fetchone=job_row)
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    claimed = _run(store.claim_next_queued("backtest", conn=conn))

    assert claimed is not None
    assert claimed["job_id"] == "stuck-1"
    assert claimed["_was_recovered"] is True
    # Existing progress / attempt are preserved (op picks up where it left off).
    assert claimed["progress"] == 42
    assert claimed["attempt"] == 2
    assert claimed["max_attempts"] == 3
    # The post-claim UPDATE should have been issued against the row.
    assert len(cursor.statements) >= 2
    assert "UPDATE backtest.backtest_jobs" in cursor.statements[1][0]


def test_claim_returns_none_when_no_candidate() -> None:
    cursor = _FakeCursor(fetchone=None)
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    claimed = _run(store.claim_next_queued("backtest", conn=conn))

    assert claimed is None
    # The SELECT happened but the follow-up UPDATE did not (no row to reset).
    assert len(cursor.statements) == 1


# ---------------------------------------------------------------- _RESET_RUNNING_SQL


def test_reset_running_sql_allows_both_queued_and_running() -> None:
    """The post-claim UPDATE must allow both queued→running and running→running."""
    cursor = _FakeCursor()
    conn = _FakeConn(cursor)
    # Pre-populate a fake "queued" claim so the second statement is fired.
    queued_row = {
        "job_id": "abc",
        "job_type": "backtest",
        "ref_id": "run-1",
        "status": "queued",
        "request_json": "{}",
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
    cursor = _FakeCursor(fetchone=queued_row)
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    _run(store.claim_next_queued("backtest", conn=conn))

    sql, params = cursor.statements[1]
    # The reset UPDATE covers both transitions.
    assert "status = 'running'" in sql
    assert "started_at = NOW()" in sql
    assert "status IN ('queued', 'running')" in sql
    assert params == {"job_id": "abc"}
