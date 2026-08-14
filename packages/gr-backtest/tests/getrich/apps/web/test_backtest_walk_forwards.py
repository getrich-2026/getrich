"""Tests for persisted walk-forward web services."""

from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from getrich.apps.web.errors import NotFound
from getrich.apps.web.pagination import PageParams
from getrich.apps.web.routers.backtest_walk_forwards import router
from getrich.apps.web.services import backtest_walk_forward


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


def _walk_forward_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "walk_forward_id": "wf-1",
        "user_id": "user-1",
        "search_type": "grid",
        "search_spec": '{"space":{"qty":["1","2"]}}',
        "select_metric": "total_return",
        "maximize": True,
        "refit": "rolling",
        "status": "completed",
        "total_windows": 2,
        "completed_windows": 1,
        "failed_windows": 1,
        "mean_validation_metric": Decimal("0.03"),
        "summary_json": '{"mean_validation_metric":"0.03"}',
        "created_at": _DT,
        "completed_at": _DT,
        "updated_at": _DT,
        "_total": 3,
    }
    row.update(overrides)
    return row


def _window_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "walk_forward_id": "wf-1",
        "window_index": 0,
        "train_start": _DT,
        "train_end": _DT,
        "val_start": _DT,
        "val_end": _DT,
        "status": "completed",
        "error_message": None,
        "train_sweep_id": "wf-1-w0000-train",
        "best_trial_id": "wf-1-w0000-train-trial-0001",
        "best_run_id": "wf-1-w0000-train-run-0001",
        "validation_run_id": "wf-1-w0000-validation",
        "best_params": '{"qty":"2"}',
        "train_metric_value": Decimal("0.05"),
        "validation_metric_value": Decimal("0.03"),
        "validation_metrics_json": '{"total_return":"0.03"}',
        "created_at": _DT,
        "completed_at": _DT,
        "updated_at": _DT,
        "_total": 2,
    }
    row.update(overrides)
    return row


def test_list_walk_forwards_returns_empty_list_and_zero_total() -> None:
    cursor = _FakeCursor(fetchall=[])
    conn = _FakeConn(cursor)

    items, total = _run(
        backtest_walk_forward.list_walk_forwards(conn, status=None, page=_PAGE, user_id="user-1")
    )

    assert items == []
    assert total == 0


def test_list_walk_forwards_maps_summary_rows_and_total() -> None:
    cursor = _FakeCursor(fetchall=[_walk_forward_row()])
    conn = _FakeConn(cursor)

    items, total = _run(
        backtest_walk_forward.list_walk_forwards(conn, status=None, page=_PAGE, user_id="user-1")
    )

    assert total == 3
    assert items[0]["walk_forward_id"] == "wf-1"
    assert items[0]["search_spec"] == {"space": {"qty": ["1", "2"]}}
    assert items[0]["mean_validation_metric"] == 0.03
    assert items[0]["created_at"].endswith("+08:00")


def test_list_walk_forwards_applies_filters_and_pagination() -> None:
    cursor = _FakeCursor(fetchall=[_walk_forward_row()])
    conn = _FakeConn(cursor)

    _run(
        backtest_walk_forward.list_walk_forwards(
            conn, status="completed", page=_PAGE, user_id="user-1"
        )
    )

    sql, params = cursor.executed[0]
    assert "COUNT(*) OVER() AS _total" in sql
    assert "user_id = %(user_id)s" in sql
    assert "status = %(status)s" in sql
    assert params == {
        "limit": 10,
        "offset": 10,
        "user_id": "user-1",
        "status": "completed",
    }


def test_list_walk_forwards_filters_rows_by_user_id() -> None:
    """Owner scoping: list_walk_forwards only returns studies owned by user_id."""
    cursor = _FakeCursor(
        fetchall=[
            _walk_forward_row(_total=2),
            _walk_forward_row(walk_forward_id="wf-2", _total=2),
        ],
    )
    conn = _FakeConn(cursor)

    items, total = _run(
        backtest_walk_forward.list_walk_forwards(conn, status=None, page=_PAGE, user_id="user-A")
    )

    assert total == 2
    assert {item["walk_forward_id"] for item in items} == {"wf-1", "wf-2"}
    sql, params = cursor.executed[0]
    assert "user_id = %(user_id)s" in sql
    assert params["user_id"] == "user-A"


def test_get_walk_forward_returns_full_detail() -> None:
    """detail includes the job linkage when the runner has claimed the
    backtest_jobs row. fetchone_seq feeds two queries: the walk_forward
    row and the backtest_jobs row."""
    cursor = _FakeCursor(
        fetchone_seq=[
            _walk_forward_row(),
            {
                "job_id": "job-wf-1",
                "ref_id": "wf-1",
                "status": "running",
                "progress": 30,
            },
        ],
    )
    conn = _FakeConn(cursor)

    data = _run(backtest_walk_forward.get_walk_forward(conn, "wf-1", user_id="user-1"))

    assert data["walk_forward_id"] == "wf-1"
    assert data["summary_json"] == {"mean_validation_metric": "0.03"}
    assert data["completed_at"].endswith("+08:00")
    # Job linkage fields:
    assert data["job_id"] == "job-wf-1"
    assert data["progress"] == 30
    assert data["job_status"] == "running"
    # SQL sanity: second call is the get_job_by_ref_id lookup.
    sql, params = cursor.executed[1]
    assert "WHERE ref_id = %(ref_id)s" in sql
    assert params == {"ref_id": "wf-1", "user_id": "user-1"}


def test_get_walk_forward_returns_null_job_fields_when_not_yet_claimed() -> None:
    """Pre-claim (or post-cleanup) the backtest_jobs row is absent;
    the detail must still load with ``None`` job linkage."""
    cursor = _FakeCursor(
        fetchone_seq=[_walk_forward_row(), None],
    )
    conn = _FakeConn(cursor)

    data = _run(backtest_walk_forward.get_walk_forward(conn, "wf-1", user_id="user-1"))

    assert data["walk_forward_id"] == "wf-1"
    assert data["job_id"] is None
    assert data["progress"] is None
    assert data["job_status"] is None


def test_get_walk_forward_does_not_leak_other_users_job_via_ref_id() -> None:
    """Cross-user probe: user-B requests user-A's walk-forward. The
    owner filter on the first query raises NotFound before the
    get_job_by_ref_id lookup runs."""
    cursor = _FakeCursor(fetchone=None)
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        _run(backtest_walk_forward.get_walk_forward(conn, "wf-1", user_id="user-B"))

    assert len(cursor.executed) == 1


def test_get_walk_forward_raises_not_found_when_missing() -> None:
    cursor = _FakeCursor(fetchone=None)
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        _run(backtest_walk_forward.get_walk_forward(conn, "missing", user_id="user-1"))


def test_get_walk_forward_raises_not_found_for_other_user() -> None:
    """Owner check: cross-user access must 404 (not leak existence)."""
    cursor = _FakeCursor(fetchone=_walk_forward_row(user_id="user-A"))
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        _run(backtest_walk_forward.get_walk_forward(conn, "wf-1", user_id="user-B"))


def test_list_windows_maps_rows_and_filters_status() -> None:
    cursor = _FakeCursor(
        fetchone=_walk_forward_row(user_id="user-1"),
        fetchall=[_window_row()],
    )
    conn = _FakeConn(cursor)

    items, total = _run(
        backtest_walk_forward.list_windows(
            conn, "wf-1", status="completed", page=_PAGE, user_id="user-1"
        )
    )

    # The second executed statement is the windows SELECT (first is the
    # parent owner-check).
    sql, params = cursor.executed[1]
    assert "walk_forward_id = %(walk_forward_id)s" in sql
    assert "status = %(status)s" in sql
    assert "ORDER BY window_index ASC" in sql
    assert params == {
        "walk_forward_id": "wf-1",
        "limit": 10,
        "offset": 10,
        "status": "completed",
    }
    assert total == 2
    assert items[0]["best_params"] == {"qty": "2"}
    assert items[0]["validation_metrics_json"] == {"total_return": "0.03"}
    assert items[0]["train_metric_value"] == 0.05
    assert items[0]["validation_metric_value"] == 0.03


def test_list_windows_raises_not_found_for_other_user() -> None:
    """Owner check: cross-user windows lookup must 404 at parent study."""
    cursor = _FakeCursor(fetchone=_walk_forward_row(user_id="user-A"))
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        _run(
            backtest_walk_forward.list_windows(
                conn, "wf-1", status=None, page=_PAGE, user_id="user-B"
            )
        )


def test_get_oos_equity_curve_returns_window_tagged_points() -> None:
    cursor = _FakeCursor(
        fetchone=_walk_forward_row(user_id="user-1"),
        fetchall=[
            {
                "walk_forward_id": "wf-1",
                "window_index": 0,
                "run_id": "validation-run",
                "strategy_name": "PersistStrategy",
                "dt": _DT,
                "cash": Decimal("900"),
                "equity": Decimal("1012"),
                "trading_pnl": Decimal("1"),
                "mtm_pnl": Decimal("12"),
                "total_fees": Decimal("0.5"),
                "gross_exposure": Decimal("112"),
                "row_json": '{"net_exposure":"112"}',
                "created_at": _DT,
            }
        ],
    )
    conn = _FakeConn(cursor)

    points = _run(backtest_walk_forward.get_oos_equity_curve(conn, "wf-1", user_id="user-1"))

    sql, params = cursor.executed[1]
    assert "JOIN backtest_equity_points" in sql
    assert params == {"walk_forward_id": "wf-1"}
    assert points[0]["walk_forward_id"] == "wf-1"
    assert points[0]["window_index"] == 0
    assert points[0]["equity"] == 1012.0
    assert points[0]["row_json"] == {"net_exposure": "112"}


def test_get_oos_equity_curve_raises_not_found_for_other_user() -> None:
    """Owner check: cross-user OOS equity lookup must 404 at parent study."""
    cursor = _FakeCursor(fetchone=_walk_forward_row(user_id="user-A"))
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        _run(backtest_walk_forward.get_oos_equity_curve(conn, "wf-1", user_id="user-B"))


def test_router_registers_backtest_walk_forward_paths() -> None:
    paths = {route.path for route in router.routes}

    assert "/backtest-walk-forwards" in paths
    assert "/backtest-walk-forwards/{walk_forward_id}" in paths
    assert "/backtest-walk-forwards/{walk_forward_id}/windows" in paths
    assert "/backtest-walk-forwards/{walk_forward_id}/oos-equity-curve" in paths
