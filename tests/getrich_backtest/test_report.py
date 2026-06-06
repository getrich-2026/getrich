import json
import tempfile
from datetime import datetime
from decimal import Decimal

import polars as pl
import pytest

from getrich_backtest import (
    AccountView,
    BacktestResult,
    Fill,
    Order,
    OrderIntent,
    OrderStatus,
    PositionView,
    Reporter,
    RunConfig,
    Side,
    compute_metrics,
    get_shanghai_tz,
)


def _result() -> BacktestResult:
    tz = get_shanghai_tz()
    config = RunConfig(
        run_id="test-report",
        strategy_name="TestStrategy",
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
        initial_cash=Decimal("1000"),
    )
    intent = OrderIntent(symbol="000001.SZ", side=Side.BUY, qty=Decimal("10"))
    order = Order(
        order_id="o1",
        intent=intent,
        strategy_name="TestStrategy",
        created_dt=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        created_index=0,
        eligible_index=1,
        status=OrderStatus.FILLED,
        filled_qty=Decimal("10"),
    )
    fill = Fill(
        fill_id="f1",
        order_id="o1",
        strategy_name="TestStrategy",
        symbol="000001.SZ",
        side=Side.BUY,
        qty=Decimal("10"),
        price=Decimal("10"),
        notional=Decimal("100"),
        fee=Decimal("0"),
        fill_time=datetime(2026, 1, 2, 9, 30, tzinfo=tz),
        bar_dt=datetime(2026, 1, 2, 9, 30, tzinfo=tz),
    )
    position_view = PositionView(symbol="000001.SZ", qty=Decimal("10"))
    account_view = AccountView(
        cash=Decimal("900"),
        positions={"000001.SZ": position_view},
    )
    equity = pl.DataFrame(
        {
            "dt": [
                datetime(2026, 1, 1, 9, 30, tzinfo=tz),
                datetime(2026, 1, 2, 9, 30, tzinfo=tz),
            ],
            "cash": [Decimal("1000"), Decimal("900")],
            "equity": [Decimal("1000"), Decimal("1012")],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )
    return BacktestResult(
        run_id="test-report",
        strategy_name="TestStrategy",
        initial_cash=Decimal("1000"),
        config=config,
        orders=(order,),
        fills=(fill,),
        final_account=account_view,
        equity_curve=equity,
    )


def test_reporter_constructs_with_result() -> None:
    reporter = Reporter(result=_result())
    assert reporter.result.strategy_name == "TestStrategy"
    assert reporter.metrics is None


def test_reporter_save_json_creates_manifest() -> None:
    result = _result()
    reporter = Reporter(result=result)
    with tempfile.TemporaryDirectory() as tmp:
        out = reporter.save(tmp, formats=("json",))

        manifest_path = out / "manifest.json"
        assert manifest_path.exists()

        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["run_id"] == "test-report"
        assert data["strategy_name"] == "TestStrategy"
        assert data["fingerprint"] == result.config.fingerprint()
        assert data["config"]["symbols"] == ["000001.SZ"]
        assert data["config"]["initial_cash"] == "1000"
        assert data["summary"]["final_equity"] == "1012"
        assert "metrics" not in data


def test_reporter_save_json_with_metrics() -> None:
    result = _result()
    metrics = compute_metrics(result, risk_free_rate=Decimal("0.03"))
    reporter = Reporter(result=result, metrics=metrics)
    with tempfile.TemporaryDirectory() as tmp:
        out = reporter.save(tmp, formats=("json",))

        data = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        assert "metrics" in data
        assert data["metrics"]["total_return"] is not None
        assert isinstance(data["metrics"]["total_return"], str)
        assert isinstance(data["metrics"]["n_bars"], int)
        assert isinstance(data["metrics"]["trading_days_per_year"], int)


def test_reporter_save_parquet_creates_files() -> None:
    result = _result()
    reporter = Reporter(result=result)
    with tempfile.TemporaryDirectory() as tmp:
        out = reporter.save(tmp, formats=("parquet",))

        assert (out / "equity.parquet").exists()
        assert (out / "fills.parquet").exists()
        assert (out / "orders.parquet").exists()

        equity_read = pl.read_parquet(str(out / "equity.parquet"))
        assert equity_read.height == 2
        assert "dt" in equity_read.columns

        fills_read = pl.read_parquet(str(out / "fills.parquet"))
        assert fills_read.height == 1
        assert fills_read["fill_id"][0] == "f1"

        orders_read = pl.read_parquet(str(out / "orders.parquet"))
        assert orders_read.height == 1
        assert orders_read["order_id"][0] == "o1"


def test_reporter_save_all_formats() -> None:
    result = _result()
    metrics = compute_metrics(result)
    reporter = Reporter(result=result, metrics=metrics)
    with tempfile.TemporaryDirectory() as tmp:
        out = reporter.save(tmp)

        assert (out / "manifest.json").exists()
        assert (out / "equity.parquet").exists()
        assert (out / "fills.parquet").exists()
        assert (out / "orders.parquet").exists()


def test_reporter_no_fills_no_orders_parquet() -> None:
    result = _result()
    # Replace with empty fills/orders
    result = BacktestResult(
        run_id=result.run_id,
        strategy_name=result.strategy_name,
        initial_cash=result.initial_cash,
        config=result.config,
        orders=(),
        fills=(),
        final_account=result.final_account,
        equity_curve=result.equity_curve,
    )
    reporter = Reporter(result=result)
    with tempfile.TemporaryDirectory() as tmp:
        out = reporter.save(tmp, formats=("parquet",))
        assert (out / "equity.parquet").exists()
        assert not (out / "fills.parquet").exists()
        assert not (out / "orders.parquet").exists()


def test_reporter_unsupported_format_raises() -> None:
    reporter = Reporter(result=_result())
    with tempfile.TemporaryDirectory() as tmp, pytest.raises(ValueError, match="unsupported"):
        reporter.save(tmp, formats=("csv",))
