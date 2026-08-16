"""Tests for persisted backtest sweep web services."""

from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from gr_api.errors import NotFound
from gr_api.pagination import PageParams
from gr_api.routers.backtest_sweeps import router
from gr_api.services import backtest_sweep


_TZ = ZoneInfo("Asia/Shanghai")
_PAGE = PageParams(page=2, page_size=10)
_DT = datetime(2026, 1, 2, 9, 30, tzinfo=_TZ)


class _FakeCursor:
    def __init__(
        self,
        *,
        fetchone: dict[str, Any] | None = None,
        fetchall: list[dict[str, Any]] | None = None,
        fetchone_seq: list[dict[str, Any] | None] | None = None,
    ) -> None:
        self.executed: list[tuple[str, dict[str, Any] | None]] = []
        self._fetchone = fetchone
        self._fetchall = fetchall or []
        self._fetchone_seq = fetchone_seq
        self._fetchone_idx = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, sql: str, params: dict[str, Any] | None = None) -> None:
        self.executed.append((sql, params))

    async def fetchone(self) -> dict[str, Any] | None:
        if self._fetchone_seq is not None:
            if self._fetchone_idx >= len(self._fetchone_seq):
                return None
            value = self._fetchone_seq[self._fetchone_idx]
            self._fetchone_idx += 1
            return value
        return self._fetchone

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._fetchall


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _FakeCursor:
        return self._cursor


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _sweep_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "sweep_id": "sweep-1",
        "user_id": "user-1",
        "search_type": "grid",
        "search_spec": '{"space":{"qty":["1","2"]}}',
        "select_metric": "total_return",
        "maximize": True,
        "status": "completed",
        "total_trials": 2,
        "completed_trials": 1,
        "failed_trials": 1,
        "best_trial_id": "sweep-1-trial-0001",
        "best_run_id": "sweep-1-run-0001",
        "best_metric_value": Decimal("0.05"),
        "summary_json": '{"best_metric_value":"0.05"}',
        "created_at": _DT,
        "completed_at": _DT,
        "updated_at": _DT,
        "_total": 3,
    }
    row.update(overrides)
    return row


def _trial_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "trial_id": "sweep-1-trial-0001",
        "sweep_id": "sweep-1",
        "run_id": "sweep-1-run-0001",
        "trial_index": 1,
        "params": '{"qty":"2"}',
        "param_fingerprint": "fingerprint-01",
        "status": "completed",
        "error_message": None,
        "select_metric_value": Decimal("0.05"),
        "metrics_json": '{"total_return":"0.05","sharpe_ratio":"1.2"}',
        "created_at": _DT,
        "completed_at": _DT,
        "updated_at": _DT,
        "_total": 2,
    }
    row.update(overrides)
    return row


def test_list_sweeps_returns_empty_list_and_zero_total() -> None:
    cursor = _FakeCursor(fetchall=[])
    conn = _FakeConn(cursor)

    items, total = _run(backtest_sweep.list_sweeps(conn, status=None, page=_PAGE, user_id="user-1"))

    assert items == []
    assert total == 0


def test_list_sweeps_maps_summary_rows_and_total() -> None:
    cursor = _FakeCursor(fetchall=[_sweep_row()])
    conn = _FakeConn(cursor)

    items, total = _run(backtest_sweep.list_sweeps(conn, status=None, page=_PAGE, user_id="user-1"))

    assert total == 3
    assert items[0]["sweep_id"] == "sweep-1"
    assert items[0]["search_spec"] == {"space": {"qty": ["1", "2"]}}
    assert items[0]["best_metric_value"] == 0.05
    assert items[0]["created_at"].endswith("+08:00")


def test_list_sweeps_applies_filters_and_pagination() -> None:
    cursor = _FakeCursor(fetchall=[_sweep_row()])
    conn = _FakeConn(cursor)

    _run(backtest_sweep.list_sweeps(conn, status="completed", page=_PAGE, user_id="user-1"))

    sql, params = cursor.executed[0]
    assert "COUNT(*) OVER() AS _total" in sql
    assert "status = %(status)s" in sql
    assert "user_id IS NOT DISTINCT FROM %(user_id)s" in sql
    assert "ORDER BY created_at DESC" in sql
    assert params == {
        "limit": 10,
        "offset": 10,
        "status": "completed",
        "user_id": "user-1",
    }


def test_list_sweeps_filters_rows_by_user_id() -> None:
    """Owner scoping: list_sweeps should only return sweeps owned by user_id."""
    cursor = _FakeCursor(
        fetchall=[_sweep_row(_total=2), _sweep_row(sweep_id="sweep-2", _total=2)],
    )
    conn = _FakeConn(cursor)

    items, total = _run(backtest_sweep.list_sweeps(conn, status=None, page=_PAGE, user_id="user-A"))

    assert total == 2
    assert {item["sweep_id"] for item in items} == {"sweep-1", "sweep-2"}
    sql, params = cursor.executed[0]
    assert "user_id IS NOT DISTINCT FROM %(user_id)s" in sql
    assert params["user_id"] == "user-A"


def test_get_sweep_returns_full_detail() -> None:
    """detail includes job linkage (job_id / progress / job_status) when the
    runner has claimed the related backtest_jobs row. fetchone_seq feeds
    two queries: get_sweep + get_job_by_ref_id.
    """
    cursor = _FakeCursor(
        fetchone_seq=[
            _sweep_row(),
            {
                "job_id": "job-1",
                "ref_id": "sweep-1",
                "status": "running",
                "progress": 42,
            },
        ],
    )
    conn = _FakeConn(cursor)

    data = _run(backtest_sweep.get_sweep(conn, "sweep-1", user_id="user-1"))

    assert data["sweep_id"] == "sweep-1"
    assert data["summary_json"] == {"best_metric_value": "0.05"}
    assert data["completed_at"].endswith("+08:00")
    # Job linkage fields:
    assert data["job_id"] == "job-1"
    assert data["progress"] == 42
    assert data["job_status"] == "running"
    # SQL sanity: the second call is the get_job_by_ref_id lookup.
    sql, params = cursor.executed[1]
    assert "WHERE ref_id = %(ref_id)s" in sql
    assert params == {"ref_id": "sweep-1", "user_id": "user-1"}


def test_get_sweep_returns_null_job_fields_when_not_yet_claimed() -> None:
    """Between job create and runner claim the backtest_jobs row is
    absent (or owned by another user). The detail must still load and
    expose the three new fields as ``None`` so the frontend falls
    back to the sweep's own status."""
    cursor = _FakeCursor(
        fetchone_seq=[_sweep_row(), None],
    )
    conn = _FakeConn(cursor)

    data = _run(backtest_sweep.get_sweep(conn, "sweep-1", user_id="user-1"))

    assert data["sweep_id"] == "sweep-1"
    assert data["job_id"] is None
    assert data["progress"] is None
    assert data["job_status"] is None


def test_get_sweep_does_not_leak_other_users_job_via_ref_id() -> None:
    """Cross-user probe: user-B requests user-A's sweep. The get_sweep
    filter is owner-scoped so it raises NotFound before we ever run
    the get_job_by_ref_id lookup. The job linkage never leaks."""
    cursor = _FakeCursor(fetchone=None)  # owner check fails
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        _run(backtest_sweep.get_sweep(conn, "sweep-1", user_id="user-B"))

    # Only the get_sweep query was executed; get_job_by_ref_id was not.
    assert len(cursor.executed) == 1


def test_get_sweep_raises_not_found_when_missing() -> None:
    cursor = _FakeCursor(fetchone=None)
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        _run(backtest_sweep.get_sweep(conn, "missing", user_id="user-1"))


def test_get_sweep_raises_not_found_for_other_user() -> None:
    """Owner check: cross-user access must 404 (not leak existence)."""
    # The store applies the user_id filter; if the row's owner does not
    # match, fetchone returns None and the service raises NotFound.
    cursor = _FakeCursor(fetchone=None)
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        _run(backtest_sweep.get_sweep(conn, "sweep-1", user_id="user-B"))

    sql, params = cursor.executed[0]
    assert "user_id IS NOT DISTINCT FROM %(user_id)s" in sql
    assert params["user_id"] == "user-B"


def test_list_sweep_trials_maps_rows_and_filters_status() -> None:
    # Two fetchone_seq values: the first for the parent sweep owner-check
    # (returns a row owned by user-1), the second unused since the trial
    # listing uses fetchall. The store's _assert_owner must see a row.
    cursor = _FakeCursor(
        fetchone_seq=[_sweep_row(user_id="user-1")],
        fetchall=[_trial_row()],
    )
    conn = _FakeConn(cursor)

    items, total = _run(
        backtest_sweep.list_sweep_trials(
            conn, "sweep-1", status="completed", page=_PAGE, user_id="user-1"
        )
    )

    # First execute is the owner-check; second is the trials SELECT.
    sql, params = cursor.executed[1]
    assert "sweep_id = %(sweep_id)s" in sql
    assert "status = %(status)s" in sql
    assert "ORDER BY trial_index" in sql
    assert params == {
        "sweep_id": "sweep-1",
        "limit": 10,
        "offset": 10,
        "status": "completed",
    }
    assert total == 2
    assert items[0]["params"] == {"qty": "2"}
    assert items[0]["metrics_json"] == {"total_return": "0.05", "sharpe_ratio": "1.2"}
    assert items[0]["select_metric_value"] == 0.05


def test_list_sweep_trials_raises_not_found_for_other_user() -> None:
    """Owner check: cross-user trial lookup must 404 at parent sweep."""
    # The store's _assert_owner calls get_sweep with the user_id filter; with
    # fetchone returning None the store raises SweepPersistenceError, which
    # the service translates to NotFound.
    cursor = _FakeCursor(fetchone=None)
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        _run(
            backtest_sweep.list_sweep_trials(
                conn, "sweep-1", status=None, page=_PAGE, user_id="user-B"
            )
        )


def test_router_registers_backtest_sweep_paths() -> None:
    paths = {route.path for route in router.routes}

    assert "/backtest-sweeps" in paths
    assert "/backtest-sweeps/{sweep_id}" in paths
    assert "/backtest-sweeps/{sweep_id}/trials" in paths
