from __future__ import annotations

import asyncio
import json
from datetime import datetime
from decimal import Decimal
from typing import Any

import polars as pl
import pytest

from getrich_backtest import (
    AccountView,
    BacktestMetrics,
    BacktestResult,
    PgSweepResultStore,
    PositionView,
    RunConfig,
    SweepResult,
    SweepTrial,
    SweepTrialResult,
    get_shanghai_tz,
)
from getrich_backtest.sweep_persistence import trials_to_frame


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
    fingerprint = f"fingerprint-{index:02d}"
    return SweepTrial(
        sweep_id="sweep-persist",
        trial_id=f"sweep-persist-trial-{index:04d}",
        run_id=f"sweep-persist-run-{index:04d}",
        index=index,
        params=params,
        param_fingerprint=fingerprint,
    )


def _sample_sweep() -> SweepResult:
    trial_0 = _trial(0, {"qty": Decimal("1"), "window": 5})
    trial_1 = _trial(1, {"qty": Decimal("2"), "window": 10})
    trial_2 = _trial(2, {"qty": Decimal("3"), "window": 20})
    return SweepResult(
        sweep_id="sweep-persist",
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
            SweepTrialResult(
                trial=trial_2,
                status="failed",
                result=None,
                metrics=None,
                error_message="bad params",
            ),
        ),
    )


def _first_params_for_sql(cursor: _FakeCursor, text: str) -> dict[str, Any]:
    for sql, params in cursor.statements:
        if text in sql:
            assert params is not None
            return params
    raise AssertionError(f"statement containing {text!r} was not executed")


def test_save_sweep_result_upserts_parent_trials_and_completed_runs() -> None:
    conn = _FakeConn()
    store = PgSweepResultStore(pool=_FakePool(conn))  # type: ignore[arg-type]

    _run(
        store.save_sweep_result(
            _sample_sweep(),
            search_spec={"type": "grid", "space": {"qty": [Decimal("1"), Decimal("2")]}},
            strategy_id="strategy-1",
        )
    )

    statements = "\n".join(sql for sql, _ in conn.cursor_obj.statements)
    many = "\n".join(sql for sql, _ in conn.cursor_obj.executemany_calls)
    assert "INSERT INTO backtest_sweeps" in statements
    assert "DELETE FROM backtest_sweep_trials" in statements
    assert "INSERT INTO backtest_sweep_trials" in many
    assert statements.count("INSERT INTO backtest_runs") == 2
    assert "INSERT INTO backtest_equity_points" in many
    assert conn.commits == 1

    sweep_params = _first_params_for_sql(conn.cursor_obj, "INSERT INTO backtest_sweeps")
    assert sweep_params["best_trial_id"] == "sweep-persist-trial-0001"
    assert sweep_params["best_run_id"] == "sweep-persist-run-0001"
    assert sweep_params["best_metric_value"] == Decimal("0.05")
    assert json.loads(sweep_params["search_spec"])["space"]["qty"] == ["1", "2"]

    trial_rows = conn.cursor_obj.executemany_calls[0][1]
    assert len(trial_rows) == 3
    assert trial_rows[0]["select_metric_value"] == Decimal("0.01")
    assert json.loads(trial_rows[0]["params"])["qty"] == "1"
    assert json.loads(trial_rows[0]["metrics_json"])["total_return"] == "0.01"
    assert trial_rows[2]["status"] == "failed"
    assert trial_rows[2]["error_message"] == "bad params"
    assert trial_rows[2]["select_metric_value"] is None
    assert json.loads(trial_rows[2]["metrics_json"]) == {}


def test_save_sweep_result_with_external_conn_does_not_commit() -> None:
    conn = _FakeConn()
    store = PgSweepResultStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    _run(store.save_sweep_result(_sample_sweep(), conn=conn))

    assert conn.commits == 0
    assert any("INSERT INTO backtest_sweeps" in sql for sql, _ in conn.cursor_obj.statements)


def test_save_sweep_result_can_skip_backtest_result_persistence() -> None:
    conn = _FakeConn()
    store = PgSweepResultStore(pool=_FakePool(conn))  # type: ignore[arg-type]

    _run(store.save_sweep_result(_sample_sweep(), save_backtest_results=False))

    statements = "\n".join(sql for sql, _ in conn.cursor_obj.statements)
    assert "INSERT INTO backtest_sweeps" in statements
    assert "INSERT INTO backtest_runs" not in statements
    assert conn.commits == 1


def test_list_sweeps_uses_status_filter_pagination_and_total() -> None:
    cursor = _FakeCursor(fetchall=[{"sweep_id": "s1", "status": "completed", "_total": 4}])
    conn = _FakeConn(cursor)
    store = PgSweepResultStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    rows, total = _run(store.list_sweeps(status="completed", limit=10, offset=20, conn=conn))

    sql, params = cursor.statements[0]
    assert "COUNT(*) OVER() AS _total" in sql
    assert "status = %(status)s" in sql
    assert "ORDER BY created_at DESC" in sql
    assert params == {"limit": 10, "offset": 20, "status": "completed"}
    assert rows == [{"sweep_id": "s1", "status": "completed"}]
    assert total == 4


@pytest.mark.parametrize("status", ["queued", "done"])
def test_list_sweeps_rejects_invalid_status(status: str) -> None:
    store = PgSweepResultStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="status must be one of"):
        _run(store.list_sweeps(status=status, conn=_FakeConn()))


def test_list_sweep_trials_uses_sweep_and_status_filters() -> None:
    cursor = _FakeCursor(fetchall=[{"trial_id": "t1", "_total": 2}])
    conn = _FakeConn(cursor)
    store = PgSweepResultStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    rows, total = _run(
        store.list_sweep_trials(
            "sweep-persist",
            status="failed",
            limit=25,
            offset=5,
            conn=conn,
        )
    )

    sql, params = cursor.statements[0]
    assert "sweep_id = %(sweep_id)s" in sql
    assert "status = %(status)s" in sql
    assert "ORDER BY trial_index" in sql
    assert params == {
        "sweep_id": "sweep-persist",
        "limit": 25,
        "offset": 5,
        "status": "failed",
    }
    assert rows == [{"trial_id": "t1"}]
    assert total == 2


def test_get_trials_frame_flattens_persisted_params_and_metrics() -> None:
    rows = [
        {
            "sweep_id": "sweep-persist",
            "trial_id": "trial-1",
            "run_id": "run-1",
            "trial_index": 1,
            "status": "completed",
            "error_message": None,
            "param_fingerprint": "abc",
            "params": '{"qty":"2","window":10}',
            "select_metric_value": Decimal("0.05"),
            "metrics_json": '{"total_return":"0.05","sharpe_ratio":"1.2"}',
        }
    ]

    frame = trials_to_frame(rows)

    assert frame.height == 1
    record = frame.to_dicts()[0]
    assert record["index"] == 1
    assert record["param_qty"] == "2"
    assert record["param_window"] == 10
    assert record["total_return"] == "0.05"
    assert record["select_metric_value"] == Decimal("0.05")


def test_get_trials_frame_loads_rows_from_store() -> None:
    cursor = _FakeCursor(
        fetchall=[
            {
                "trial_id": "trial-1",
                "trial_index": 0,
                "params": {"qty": "1"},
                "metrics_json": {"total_return": "0.01"},
                "_total": 1,
            }
        ]
    )
    conn = _FakeConn(cursor)
    store = PgSweepResultStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    frame = _run(store.get_trials_frame("sweep-persist", conn=conn))

    assert frame.height == 1
    assert frame.to_dicts()[0]["param_qty"] == "1"
