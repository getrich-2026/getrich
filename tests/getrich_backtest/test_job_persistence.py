"""Tests for the PostgreSQL-backed backtest job store."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest

from getrich_backtest import BacktestJobError, PgBacktestJobStore


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
        # If the SQL was a SELECT that returned a row, surface it.
        if "SELECT" in sql.upper() and self._fetchone is not None and "FOR UPDATE" in sql.upper():
            self._fetchone_captured = self._fetchone

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


def _first_params_for_sql(cursor: _FakeCursor, text: str) -> dict[str, Any]:
    for sql, params in cursor.statements:
        if text in sql:
            assert params is not None
            return params
    raise AssertionError(f"statement containing {text!r} was not executed")


def test_create_job_inserts_queued_row_and_returns_uuid() -> None:
    cursor = _FakeCursor()
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(conn))  # type: ignore[arg-type]

    job_id = _run(store.create_job("backtest", "run-1", request_json={"x": 1}))

    assert len(job_id) == 32  # uuid4().hex
    assert conn.commits == 1
    sql, params = cursor.statements[0]
    assert "INSERT INTO backtest_jobs" in sql
    assert params["job_type"] == "backtest"
    assert params["ref_id"] == "run-1"
    assert json.loads(params["request_json"]) == {"x": 1}


def test_create_job_serializes_decimal_and_datetime_in_request_json() -> None:
    cursor = _FakeCursor()
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(conn))  # type: ignore[arg-type]

    _run(
        store.create_job(
            "backtest",
            "run-2",
            request_json={"amount": Decimal("1.25"), "ts": datetime(2026, 6, 2, 9, 30)},
        )
    )

    sql, params = cursor.statements[0]
    decoded = json.loads(params["request_json"])
    assert decoded["amount"] == "1.25"
    assert "2026-06-02T09:30:00" in decoded["ts"]


def test_create_job_with_external_conn_does_not_commit() -> None:
    cursor = _FakeCursor()
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    _run(store.create_job("backtest", "run-3", conn=conn))

    assert conn.commits == 0


def test_create_job_rejects_invalid_job_type() -> None:
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="job_type must be one of"):
        _run(store.create_job("invalid", "run-1"))


def test_create_job_rejects_empty_ref_id() -> None:
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="ref_id must be non-empty"):
        _run(store.create_job("backtest", "  "))


def test_claim_next_queued_returns_row_and_marks_running() -> None:
    job_row = {
        "job_id": "abc",
        "job_type": "backtest",
        "ref_id": "run-1",
        "status": "queued",
        "request_json": "{}",
        "progress": 0,
        "error_message": None,
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
    assert claimed["job_id"] == "abc"
    assert claimed["status"] == "running"
    assert "FOR UPDATE SKIP LOCKED" in cursor.statements[0][0]
    assert "UPDATE backtest_jobs" in cursor.statements[1][0]
    assert conn.commits == 0


def test_claim_next_queued_returns_none_when_empty() -> None:
    cursor = _FakeCursor(fetchone=None)
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    claimed = _run(store.claim_next_queued("backtest", conn=conn))

    assert claimed is None
    assert "FOR UPDATE SKIP LOCKED" in cursor.statements[0][0]
    # No follow-up UPDATE should be issued.
    assert not any("UPDATE backtest_jobs" in sql for sql, _ in cursor.statements[1:])


def test_claim_next_queued_rejects_invalid_job_type() -> None:
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="job_type must be one of"):
        _run(store.claim_next_queued("invalid"))


def test_mark_running_uses_queued_to_running_sql() -> None:
    cursor = _FakeCursor()
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    ok = _run(store.mark_running("job-1", conn=conn))

    assert ok is True
    sql, params = cursor.statements[0]
    assert "status = 'running'" in sql
    assert "status = 'queued'" in sql
    assert params == {"job_id": "job-1"}


def test_update_progress_writes_clamped_value() -> None:
    cursor = _FakeCursor()
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    _run(store.update_progress("job-1", 250, conn=conn))

    sql, params = cursor.statements[0]
    assert "progress = %(progress)s" in sql
    assert params == {"job_id": "job-1", "progress": 100}


def test_mark_completed_runs_terminal_sql() -> None:
    cursor = _FakeCursor()
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    _run(store.mark_completed("job-1", conn=conn))

    sql, params = cursor.statements[0]
    assert "status = 'completed'" in sql
    assert "progress = 100" in sql
    assert params == {"job_id": "job-1"}


def test_mark_failed_writes_error_message() -> None:
    cursor = _FakeCursor()
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    _run(store.mark_failed("job-1", "boom", conn=conn))

    sql, params = cursor.statements[0]
    assert "status = 'failed'" in sql
    assert "error_message = %(error_message)s" in sql
    assert params == {"job_id": "job-1", "error_message": "boom"}


def test_mark_cancelled_only_from_queued_or_running() -> None:
    cursor = _FakeCursor()
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    _run(store.mark_cancelled("job-1", conn=conn))

    sql = cursor.statements[0][0]
    assert "status = 'cancelled'" in sql
    assert "status IN ('queued', 'running')" in sql


def test_get_job_returns_row_when_present() -> None:
    row = {
        "job_id": "job-1",
        "job_type": "backtest",
        "ref_id": "run-1",
        "user_id": None,
        "status": "queued",
        "request_json": "{}",
        "progress": 0,
        "error_message": None,
        "created_at": datetime(2026, 6, 2, 9, 30),
        "started_at": None,
        "completed_at": None,
        "updated_at": datetime(2026, 6, 2, 9, 30),
    }
    cursor = _FakeCursor(fetchone=row)
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    out = _run(store.get_job("job-1", conn=conn))

    assert out is not None
    assert out["job_id"] == "job-1"
    sql, params = cursor.statements[0]
    assert sql.strip().startswith("SELECT")
    # ``user_id`` is now a real column in the WHERE clause; ``conn=`` (no
    # user_id passed) is the system/bypass path. The store forwards
    # ``user_id=None`` to the SQL ``%(user_id)s`` param.
    assert params == {"job_id": "job-1", "user_id": None}


def test_get_job_returns_none_when_missing() -> None:
    cursor = _FakeCursor(fetchone=None)
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    out = _run(store.get_job("missing", conn=conn))

    assert out is None


# ---------------------------------------------------------------- get_job_by_ref_id


def test_get_job_by_ref_id_returns_row_when_present() -> None:
    """A matching ``ref_id`` returns the row and forwards the right SQL params."""
    row = {
        "job_id": "job-1",
        "job_type": "sweep",
        "ref_id": "sweep-abc",
        "user_id": "user-1",
        "status": "running",
        "request_json": "{}",
        "request_hash": None,
        "progress": 42,
        "error_message": None,
        "attempt": 1,
        "max_attempts": 1,
        "next_retry_at": None,
        "retry_base_seconds": None,
        "retry_cap_seconds": None,
        "retry_jitter_pct": None,
        "created_at": datetime(2026, 6, 5, 9, 30),
        "started_at": datetime(2026, 6, 5, 9, 30),
        "completed_at": None,
        "updated_at": datetime(2026, 6, 5, 9, 30),
    }
    cursor = _FakeCursor(fetchone=row)
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    out = _run(store.get_job_by_ref_id("sweep-abc", user_id="user-1", conn=conn))

    assert out is not None
    assert out["job_id"] == "job-1"
    assert out["ref_id"] == "sweep-abc"
    assert out["progress"] == 42
    sql, params = cursor.statements[0]
    assert "WHERE ref_id = %(ref_id)s" in sql
    # ``ORDER BY created_at DESC LIMIT 1`` keeps the lookup deterministic
    # when a retry reuses the same ``ref_id``.
    assert "ORDER BY created_at DESC" in sql
    assert "LIMIT 1" in sql
    assert params == {"ref_id": "sweep-abc", "user_id": "user-1"}


def test_get_job_by_ref_id_returns_none_when_missing() -> None:
    """A non-existent ref_id returns None (no exception)."""
    cursor = _FakeCursor(fetchone=None)
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    out = _run(store.get_job_by_ref_id("vanished", conn=conn))

    assert out is None


def test_get_job_by_ref_id_forwards_user_id_for_owner_scoping() -> None:
    """The caller is responsible for passing the right user_id — the SQL
    does the owner-scope filter via ``user_id IS NOT DISTINCT FROM``.
    We only verify the params are forwarded (the SQL ``OR`` itself is
    covered by the get_job tests)."""
    cursor = _FakeCursor(fetchone=None)
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    _run(store.get_job_by_ref_id("sweep-x", user_id="user-7", conn=conn))

    sql, params = cursor.statements[0]
    assert params == {"ref_id": "sweep-x", "user_id": "user-7"}


def test_get_job_by_ref_id_with_star_sentinel_bypasses_owner_scope() -> None:
    """``user_id="*"`` is the system/runner sentinel — the SQL ``OR`` arm
    matches the row regardless of the owner column. We assert the
    sentinel is forwarded as-is so the SQL layer can interpret it."""
    cursor = _FakeCursor(fetchone=None)
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    _run(store.get_job_by_ref_id("any", user_id="*", conn=conn))

    sql, params = cursor.statements[0]
    assert params == {"ref_id": "any", "user_id": "*"}


def test_list_jobs_uses_filters_pagination_and_total() -> None:
    row = {
        "job_id": "job-1",
        "job_type": "backtest",
        "ref_id": "run-1",
        "status": "queued",
        "request_json": "{}",
        "progress": 0,
        "error_message": None,
        "created_at": datetime(2026, 6, 2, 9, 30),
        "started_at": None,
        "completed_at": None,
        "updated_at": datetime(2026, 6, 2, 9, 30),
        "_total": 4,
    }
    cursor = _FakeCursor(fetchall=[row])
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    rows, total = _run(
        store.list_jobs(job_type="backtest", status="queued", limit=10, offset=0, conn=conn)
    )

    assert total == 4
    assert rows[0]["job_id"] == "job-1"
    assert "_total" not in rows[0]
    sql, params = cursor.statements[0]
    assert "COUNT(*) OVER() AS _total" in sql
    assert "job_type = %(job_type)s" in sql
    assert "status = %(status)s" in sql
    assert params == {"limit": 10, "offset": 0, "job_type": "backtest", "status": "queued"}


def test_list_jobs_returns_empty_and_zero_total_when_no_rows() -> None:
    cursor = _FakeCursor(fetchall=[])
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    rows, total = _run(store.list_jobs(conn=conn))

    assert rows == []
    assert total == 0


@pytest.mark.parametrize("status", ["queued", "running", "completed", "failed", "cancelled"])
def test_list_jobs_accepts_every_status(status: str) -> None:
    cursor = _FakeCursor(fetchall=[])
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    _run(store.list_jobs(status=status, conn=conn))

    sql, params = cursor.statements[0]
    assert "status = %(status)s" in sql
    assert params["status"] == status


@pytest.mark.parametrize("status", ["pending", "done", "unknown"])
def test_list_jobs_rejects_invalid_status(status: str) -> None:
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="status must be one of"):
        _run(store.list_jobs(status=status, conn=_FakeConn(_FakeCursor())))


@pytest.mark.parametrize("job_type", ["unknown", "execute"])
def test_list_jobs_rejects_invalid_job_type(job_type: str) -> None:
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="job_type must be one of"):
        _run(store.list_jobs(job_type=job_type, conn=_FakeConn(_FakeCursor())))


def test_list_jobs_rejects_bad_pagination() -> None:
    store = PgBacktestJobStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="limit must be positive"):
        _run(store.list_jobs(limit=0, conn=_FakeConn(_FakeCursor())))
    with pytest.raises(ValueError, match="offset must be non-negative"):
        _run(store.list_jobs(offset=-1, conn=_FakeConn(_FakeCursor())))


def test_create_job_wraps_unexpected_errors() -> None:
    class _BoomCursor(_FakeCursor):
        async def execute(self, sql, params=None):  # type: ignore[override]
            raise RuntimeError("db is down")

    cursor = _BoomCursor()
    conn = _FakeConn(cursor)
    store = PgBacktestJobStore(pool=_FakePool(conn))  # type: ignore[arg-type]

    with pytest.raises(BacktestJobError, match="failed to create job"):
        _run(store.create_job("backtest", "run-1"))


def test_public_api_exports_job_persistence() -> None:
    from getrich_backtest import (
        BacktestJobError as ExportedError,
        PgBacktestJobStore as ExportedStore,
    )

    assert ExportedStore is PgBacktestJobStore
    assert ExportedError is BacktestJobError
