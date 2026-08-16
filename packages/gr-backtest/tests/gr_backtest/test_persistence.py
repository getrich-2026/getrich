import asyncio
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl
from gr_backtest import (
    AccountView,
    BacktestArtifact,
    BacktestResult,
    PgBacktestResultStore,
    PositionView,
    RunConfig,
    artifacts_from_report_dir,
    compute_metrics,
    get_shanghai_tz,
)
from gr_backtest.persistence import (
    _equity_rows,
    _metrics_params,
    _position_rows,
    _run_params,
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


def _sample_result(*, extra_equity_col: bool = False) -> BacktestResult:
    tz = get_shanghai_tz()
    config = RunConfig(
        run_id="run-persist",
        strategy_name="PersistStrategy",
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 3, 9, 30, tzinfo=tz),
        initial_cash=Decimal("1000"),
        created_at=datetime(2026, 1, 1, 8, 0, tzinfo=tz),
    )
    data: dict[str, object] = {
        "dt": [
            datetime(2026, 1, 1, 9, 30, tzinfo=tz),
            datetime(2026, 1, 2, 9, 30, tzinfo=tz),
        ],
        "cash": [Decimal("1000"), Decimal("900")],
        "equity": [Decimal("1000"), Decimal("1012")],
        "trading_pnl": [Decimal("0"), Decimal("0")],
        "mtm_pnl": [Decimal("0"), Decimal("12")],
        "total_fees": [Decimal("0"), Decimal("0")],
        "gross_exposure": [Decimal("0"), Decimal("112")],
    }
    if extra_equity_col:
        data["net_exposure"] = [Decimal("0"), Decimal("112")]
    equity = pl.DataFrame(data, schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")})
    account = AccountView(
        cash=Decimal("900"),
        positions={"000001.SZ": PositionView(symbol="000001.SZ", qty=Decimal("10"))},
        available_cash=Decimal("900"),
        maintenance_margin=Decimal("0"),
    )
    return BacktestResult(
        run_id="run-persist",
        strategy_name="PersistStrategy",
        initial_cash=Decimal("1000"),
        config=config,
        orders=(),
        fills=(),
        final_account=account,
        equity_curve=equity,
    )


def test_run_params_preserve_decimal_and_config_json() -> None:
    result = _sample_result()

    params = _run_params(result, strategy_id="strategy-1", status="completed")
    config = json.loads(params["config"])

    assert params["initial_cash"] == Decimal("1000")
    assert params["final_cash"] == Decimal("900")
    assert params["final_equity"] == Decimal("1012")
    assert config["initial_cash"] == "1000"
    assert config["start"].endswith("+08:00")
    assert json.loads(params["symbols"]) == ["000001.SZ"]


def test_metrics_params_preserve_decimal() -> None:
    result = _sample_result()
    metrics = compute_metrics(result)

    params = _metrics_params(metrics)

    assert isinstance(params["total_return"], Decimal)
    assert isinstance(params["total_fees"], Decimal)
    assert not isinstance(params["total_return"], float)
    assert json.loads(params["metrics_json"])["total_return"] == str(metrics.total_return)


def test_equity_rows_include_known_columns_and_row_json() -> None:
    result = _sample_result(extra_equity_col=True)

    rows = _equity_rows(result)

    assert rows[0]["strategy_name"] == "PersistStrategy"
    assert rows[1]["equity"] == Decimal("1012")
    assert rows[1]["gross_exposure"] == Decimal("112")
    assert json.loads(rows[1]["row_json"]) == {"net_exposure": "112"}


def test_final_positions_from_account_view() -> None:
    rows = _position_rows(_sample_result())

    assert rows == [
        {
            "run_id": "run-persist",
            "symbol": "000001.SZ",
            "qty": Decimal("10"),
            "position_json": '{"symbol":"000001.SZ","qty":"10"}',
        }
    ]


def test_multi_strategy_equity_rows_preserve_strategy_name_column() -> None:
    result = _sample_result()
    result = BacktestResult(
        run_id=result.run_id,
        strategy_name="_combined",
        initial_cash=result.initial_cash,
        config=result.config,
        orders=(),
        fills=(),
        final_account=result.final_account,
        equity_curve=result.equity_curve.with_columns(pl.Series("strategy_name", ["Fast", "Slow"])),
    )

    rows = _equity_rows(result)

    assert [row["strategy_name"] for row in rows] == ["Fast", "Slow"]


def test_save_result_executes_upsert_delete_insert_commit() -> None:
    result = _sample_result()
    metrics = compute_metrics(result)
    conn = _FakeConn()
    store = PgBacktestResultStore(pool=_FakePool(conn))  # type: ignore[arg-type]

    _run(
        store.save_result(
            result,
            metrics=metrics,
            artifacts=[BacktestArtifact("manifest", "/tmp/m.json")],
        )
    )

    statements = "\n".join(sql for sql, _ in conn.cursor_obj.statements)
    many = "\n".join(sql for sql, _ in conn.cursor_obj.executemany_calls)
    assert "INSERT INTO backtest.backtest_runs" in statements
    assert "DELETE FROM backtest.backtest_metrics" in statements
    assert "DELETE FROM backtest.backtest_equity_points" in statements
    assert "INSERT INTO backtest.backtest_metrics" in statements
    assert "INSERT INTO backtest.backtest_equity_points" in many
    assert "INSERT INTO backtest.backtest_final_positions" in many
    assert "INSERT INTO backtest.backtest_artifacts" in many
    assert conn.commits == 1


def test_save_result_with_external_conn_does_not_commit() -> None:
    conn = _FakeConn()
    store = PgBacktestResultStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    _run(store.save_result(_sample_result(), conn=conn))

    assert conn.commits == 0
    assert any("INSERT INTO backtest.backtest_runs" in sql for sql, _ in conn.cursor_obj.statements)


def test_mark_running_upserts_running_status_without_child_writes() -> None:
    conn = _FakeConn()
    store = PgBacktestResultStore(pool=_FakePool(conn))  # type: ignore[arg-type]

    _run(store.mark_running(_sample_result().config))

    statements = "\n".join(sql for sql, _ in conn.cursor_obj.statements)
    assert "INSERT INTO backtest.backtest_runs" in statements
    assert "backtest_metrics" not in statements
    assert conn.cursor_obj.statements[0][1]["status"] == "running"
    assert conn.commits == 1


def test_mark_failed_records_error_and_commit() -> None:
    conn = _FakeConn()
    store = PgBacktestResultStore(pool=_FakePool(conn))  # type: ignore[arg-type]

    _run(store.mark_failed(_sample_result().config, "boom"))

    params = conn.cursor_obj.statements[0][1]
    assert params["status"] == "failed"
    assert params["error_message"] == "boom"
    assert conn.commits == 1


def test_list_runs_uses_count_window_and_filters() -> None:
    cursor = _FakeCursor(fetchall=[{"run_id": "r1", "_total": 3}])
    conn = _FakeConn(cursor)
    store = PgBacktestResultStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    rows, total = _run(
        store.list_runs(strategy_id="s1", status="completed", limit=10, offset=20, conn=conn)
    )

    sql, params = cursor.statements[0]
    assert "COUNT(*) OVER() AS _total" in sql
    assert "strategy_id = %(strategy_id)s" in sql
    assert "status = %(status)s" in sql
    assert params == {"limit": 10, "offset": 20, "strategy_id": "s1", "status": "completed"}
    assert rows == [{"run_id": "r1"}]
    assert total == 3


def test_get_equity_curve_filters_strategy_name() -> None:
    cursor = _FakeCursor(fetchall=[])
    conn = _FakeConn(cursor)
    store = PgBacktestResultStore(pool=_FakePool(_FakeConn()))  # type: ignore[arg-type]

    _run(store.get_equity_curve("run-1", strategy_name="Fast", conn=conn))

    sql, params = cursor.statements[0]
    assert "strategy_name = %(strategy_name)s" in sql
    assert params == {"run_id": "run-1", "strategy_name": "Fast"}


def test_artifacts_from_report_dir_detects_existing_files(tmp_path: Path) -> None:
    for name in [
        "manifest.json",
        "equity.parquet",
        "fills.parquet",
        "orders.parquet",
        "tear_sheet.html",
    ]:
        (tmp_path / name).write_text("x", encoding="utf-8")

    artifacts = artifacts_from_report_dir(tmp_path)

    assert [(a.artifact_type, Path(a.uri).name) for a in artifacts] == [
        ("manifest", "manifest.json"),
        ("equity_parquet", "equity.parquet"),
        ("fills_parquet", "fills.parquet"),
        ("orders_parquet", "orders.parquet"),
        ("html", "tear_sheet.html"),
    ]
