from __future__ import annotations

import asyncio
import json
from datetime import datetime
from decimal import Decimal
from typing import Any

import polars as pl
import pytest
from gr_backtest import (
    AccountView,
    BacktestMetrics,
    BacktestResult,
    PgWalkForwardResultStore,
    PgWalkForwardResultStore as ExportedStore,
    PositionView,
    RunConfig,
    SweepResult,
    SweepTrial,
    SweepTrialResult,
    WalkForwardResult,
    WalkForwardWindow,
    WalkForwardWindowResult,
    get_shanghai_tz,
    walk_forward_windows_to_frame,
    walk_forward_windows_to_frame as exported_frame,
)


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
    ) -> None:
        self.statements: list[tuple[str, dict[str, Any] | None]] = []
        self.executemany_calls: list[tuple[str, list[dict[str, Any]]]] = []
        self._fetchone = fetchone
        self._fetchall = fetchall or []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, sql: str, params: dict[str, Any] | None = None) -> None:
        self.statements.append((sql, params))

    async def executemany(self, sql: str, rows: list[dict[str, Any]]) -> None:
        self.executemany_calls.append((sql, rows))

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


def _metrics(run_id: str, *, total_return: Decimal) -> BacktestMetrics:
    return BacktestMetrics(
        strategy_name="PersistStrategy",
        run_id=run_id,
        total_return=total_return,
        log_return=Decimal("0.01"),
        annualized_return=Decimal("0.10"),
        annualized_volatility=Decimal("0.20"),
        sharpe_ratio=total_return * Decimal("10"),
        sortino_ratio=Decimal("1.50"),
        calmar_ratio=Decimal("2.00"),
        max_drawdown=Decimal("0.05"),
        max_drawdown_duration=2,
        total_fees=Decimal("1.23"),
        total_turnover=Decimal("100.00"),
        turnover_rate=Decimal("0.10"),
        total_trades=1,
        n_bars=2,
        risk_free_rate=Decimal("0.03"),
        trading_days_per_year=252,
    )


def _sample_result(run_id: str, params: dict[str, object]) -> BacktestResult:
    tz = get_shanghai_tz()
    config = RunConfig(
        run_id=run_id,
        strategy_name="PersistStrategy",
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 3, 9, 30, tzinfo=tz),
        initial_cash=Decimal("1000"),
        created_at=datetime(2026, 1, 1, 8, 0, tzinfo=tz),
        strategy_params=params,
    )
    equity = pl.DataFrame(
        {
            "dt": [
                datetime(2026, 1, 1, 9, 30, tzinfo=tz),
                datetime(2026, 1, 2, 9, 30, tzinfo=tz),
            ],
            "cash": [Decimal("1000"), Decimal("900")],
            "equity": [Decimal("1000"), Decimal("1012")],
            "trading_pnl": [Decimal("0"), Decimal("0")],
            "mtm_pnl": [Decimal("0"), Decimal("12")],
            "total_fees": [Decimal("0"), Decimal("1.23")],
            "gross_exposure": [Decimal("0"), Decimal("112")],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )
    account = AccountView(
        cash=Decimal("900"),
        positions={"000001.SZ": PositionView(symbol="000001.SZ", qty=Decimal("10"))},
        available_cash=Decimal("900"),
        maintenance_margin=Decimal("0"),
    )
    return BacktestResult(
        run_id=run_id,
        strategy_name="PersistStrategy",
        initial_cash=Decimal("1000"),
        config=config,
        orders=(),
        fills=(),
        final_account=account,
        equity_curve=equity,
    )


def _trial(index: int, params: dict[str, object]) -> SweepTrial:
    return SweepTrial(
        sweep_id="wf-persist-w0000-train",
        trial_id=f"wf-persist-w0000-train-trial-{index:04d}",
        run_id=f"wf-persist-w0000-train-run-{index:04d}",
        index=index,
        params=params,
        param_fingerprint=f"fingerprint-{index:02d}",
    )


def _sample_sweep() -> SweepResult:
    trial_0 = _trial(0, {"qty": Decimal("1"), "window": 5})
    trial_1 = _trial(1, {"qty": Decimal("2"), "window": 10})
    return SweepResult(
        sweep_id="wf-persist-w0000-train",
        select_metric="total_return",
        maximize=True,
        trials=(
            SweepTrialResult(
                trial=trial_0,
                status="completed",
                result=_sample_result(trial_0.run_id, dict(trial_0.params)),
                metrics=_metrics(trial_0.run_id, total_return=Decimal("0.01")),
            ),
            SweepTrialResult(
                trial=trial_1,
                status="completed",
                result=_sample_result(trial_1.run_id, dict(trial_1.params)),
                metrics=_metrics(trial_1.run_id, total_return=Decimal("0.05")),
            ),
        ),
    )


def _window(index: int) -> WalkForwardWindow:
    tz = get_shanghai_tz()
    return WalkForwardWindow(
        index=index,
        train_start=datetime(2026, 1, 1 + index, 9, 30, tzinfo=tz),
        train_end=datetime(2026, 2, 1 + index, 9, 30, tzinfo=tz),
        val_start=datetime(2026, 2, 1 + index, 9, 30, tzinfo=tz),
        val_end=datetime(2026, 3, 1 + index, 9, 30, tzinfo=tz),
    )


def _sample_walk_forward() -> WalkForwardResult:
    sweep = _sample_sweep()
    best_trial = sweep.best_trial(metric="total_return", maximize=True)
    validation_result = _sample_result("wf-persist-w0000-validation", dict(best_trial.trial.params))
    return WalkForwardResult(
        walk_forward_id="wf-persist",
        windows=(
            WalkForwardWindowResult(
                window=_window(0),
                train_sweep=sweep,
                best_trial=best_trial,
                validation_result=validation_result,
                validation_metrics=_metrics(validation_result.run_id, total_return=Decimal("0.03")),
                status="completed",
            ),
            WalkForwardWindowResult(
                window=_window(1),
                train_sweep=None,
                best_trial=None,
                validation_result=None,
                validation_metrics=None,
                status="failed",
                error_message="validation failed",
            ),
        ),
        select_metric="total_return",
        maximize=True,
        refit="rolling",
    )


def _first_params_for_sql(cursor: _FakeCursor, text: str) -> dict[str, Any]:
    for sql, params in cursor.statements:
        if text in sql:
            assert params is not None
            return params
    raise AssertionError(f"statement containing {text!r} was not executed")


def test_save_walk_forward_result_upserts_parent_windows_and_child_results() -> None:
    conn = _FakeConn()
    store = PgWalkForwardResultStore(pool=_FakePool(conn))  # type: ignore[arg-type]

    _run(
        store.save_walk_forward_result(
            _sample_walk_forward(),
            search_spec={"space": {"qty": [Decimal("1"), Decimal("2")]}},
        )
    )

    statements = "\n".join(sql for sql, _ in conn.cursor_obj.statements)
    many = "\n".join(sql for sql, _ in conn.cursor_obj.executemany_calls)
    assert "INSERT INTO backtest.backtest_walk_forwards" in statements
    assert "DELETE FROM backtest.backtest_walk_forward_windows" in statements
    assert "INSERT INTO backtest.backtest_walk_forward_windows" in many
    assert "INSERT INTO backtest.backtest_sweeps" in statements
    assert statements.count("INSERT INTO backtest.backtest_runs") == 3
    assert conn.commits == 1

    parent_params = _first_params_for_sql(
        conn.cursor_obj, "INSERT INTO backtest.backtest_walk_forwards"
    )
    assert parent_params["walk_forward_id"] == "wf-persist"
    assert parent_params["completed_windows"] == 1
    assert parent_params["failed_windows"] == 1
    assert json.loads(parent_params["search_spec"])["space"]["qty"] == ["1", "2"]

    window_rows = conn.cursor_obj.executemany_calls[0][1]
    assert len(window_rows) == 2
    assert window_rows[0]["walk_forward_id"] == "wf-persist"
    assert window_rows[0]["status"] == "completed"
    assert window_rows[0]["train_sweep_id"] == "wf-persist-w0000-train"
    assert window_rows[0]["best_trial_id"] == "wf-persist-w0000-train-trial-0001"
    assert window_rows[0]["validation_run_id"] == "wf-persist-w0000-validation"
    assert window_rows[0]["train_metric_value"] == Decimal("0.05")
    assert window_rows[0]["validation_metric_value"] == Decimal("0.03")
    assert json.loads(window_rows[0]["best_params"])["qty"] == "2"
    assert json.loads(window_rows[0]["validation_metrics_json"])["total_return"] == "0.03"
    assert window_rows[1]["status"] == "failed"
    assert window_rows[1]["error_message"] == "validation failed"


def test_save_walk_forward_result_with_external_conn_does_not_commit() -> None:
    conn = _FakeConn()
    store = PgWalkForwardResultStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    _run(store.save_walk_forward_result(_sample_walk_forward(), conn=conn))

    assert conn.commits == 0
    assert any(
        "INSERT INTO backtest.backtest_walk_forwards" in sql
        for sql, _ in conn.cursor_obj.statements
    )


def test_save_walk_forward_result_can_skip_child_result_persistence() -> None:
    conn = _FakeConn()
    store = PgWalkForwardResultStore(pool=_FakePool(conn))  # type: ignore[arg-type]

    _run(store.save_walk_forward_result(_sample_walk_forward(), save_child_results=False))

    statements = "\n".join(sql for sql, _ in conn.cursor_obj.statements)
    assert "INSERT INTO backtest.backtest_walk_forwards" in statements
    assert "INSERT INTO backtest.backtest_sweeps" not in statements
    assert "INSERT INTO backtest.backtest_runs" not in statements
    assert conn.commits == 1


def test_list_walk_forwards_uses_status_filter_pagination_and_total() -> None:
    cursor = _FakeCursor(fetchall=[{"walk_forward_id": "wf-1", "status": "completed", "_total": 4}])
    conn = _FakeConn(cursor)
    store = PgWalkForwardResultStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    rows, total = _run(store.list_walk_forwards(status="completed", limit=10, offset=20, conn=conn))

    sql, params = cursor.statements[0]
    assert "COUNT(*) OVER() AS _total" in sql
    assert "status = %(status)s" in sql
    assert "ORDER BY created_at DESC" in sql
    assert params == {"limit": 10, "offset": 20, "status": "completed"}
    assert rows == [{"walk_forward_id": "wf-1", "status": "completed"}]
    assert total == 4


@pytest.mark.parametrize("status", ["queued", "done"])
def test_list_walk_forwards_rejects_invalid_status(status: str) -> None:
    store = PgWalkForwardResultStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="status must be one of"):
        _run(store.list_walk_forwards(status=status, conn=_FakeConn()))


def test_list_windows_uses_walk_forward_and_status_filters() -> None:
    cursor = _FakeCursor(fetchall=[{"window_index": 1, "_total": 2}])
    conn = _FakeConn(cursor)
    store = PgWalkForwardResultStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    rows, total = _run(
        store.list_windows(
            "wf-persist",
            status="failed",
            limit=25,
            offset=5,
            conn=conn,
        )
    )

    sql, params = cursor.statements[0]
    assert "walk_forward_id = %(walk_forward_id)s" in sql
    assert "status = %(status)s" in sql
    assert "ORDER BY window_index" in sql
    assert params == {
        "walk_forward_id": "wf-persist",
        "limit": 25,
        "offset": 5,
        "status": "failed",
    }
    assert rows == [{"window_index": 1}]
    assert total == 2


def test_walk_forward_windows_to_frame_flattens_params_and_metrics() -> None:
    rows = [
        {
            "walk_forward_id": "wf-persist",
            "window_index": 0,
            "status": "completed",
            "best_params": '{"qty":"2","window":10}',
            "train_metric_value": Decimal("0.05"),
            "validation_metric_value": Decimal("0.03"),
            "validation_metrics_json": '{"total_return":"0.03","sharpe_ratio":"1.2"}',
        }
    ]

    frame = walk_forward_windows_to_frame(rows)

    assert frame.height == 1
    record = frame.to_dicts()[0]
    assert record["window_index"] == 0
    assert record["param_qty"] == "2"
    assert record["param_window"] == 10
    assert record["validation_total_return"] == "0.03"
    assert record["validation_metric_value"] == Decimal("0.03")


def test_get_windows_frame_loads_rows_from_store() -> None:
    cursor = _FakeCursor(
        fetchall=[
            {
                "window_index": 0,
                "best_params": {"qty": "1"},
                "validation_metrics_json": {"total_return": "0.01"},
                "_total": 1,
            }
        ]
    )
    conn = _FakeConn(cursor)
    store = PgWalkForwardResultStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    frame = _run(store.get_windows_frame("wf-persist", conn=conn))

    assert frame.height == 1
    assert frame.to_dicts()[0]["param_qty"] == "1"


def test_get_oos_equity_curve_returns_window_tagged_frame() -> None:
    tz = get_shanghai_tz()
    cursor = _FakeCursor(
        fetchall=[
            {
                "walk_forward_id": "wf-persist",
                "window_index": 0,
                "run_id": "validation-run",
                "strategy_name": "PersistStrategy",
                "dt": datetime(2026, 2, 1, 9, 30, tzinfo=tz),
                "cash": Decimal("900"),
                "equity": Decimal("1012"),
                "trading_pnl": Decimal("0"),
                "mtm_pnl": Decimal("12"),
                "total_fees": Decimal("1.23"),
                "gross_exposure": Decimal("112"),
                "row_json": '{"net_exposure":"112"}',
                "created_at": datetime(2026, 2, 1, 9, 31, tzinfo=tz),
            }
        ]
    )
    conn = _FakeConn(cursor)
    store = PgWalkForwardResultStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    frame = _run(store.get_oos_equity_curve("wf-persist", conn=conn))

    sql, params = cursor.statements[0]
    assert "JOIN backtest.backtest_equity_points" in sql
    assert params == {"walk_forward_id": "wf-persist"}
    record = frame.to_dicts()[0]
    assert record["walk_forward_id"] == "wf-persist"
    assert record["window_index"] == 0
    assert record["run_id"] == "validation-run"
    assert record["equity"] == Decimal("1012")
    assert record["row_json"] == {"net_exposure": "112"}


def test_public_api_exports_walk_forward_persistence() -> None:
    assert ExportedStore is PgWalkForwardResultStore
    assert exported_frame is walk_forward_windows_to_frame
