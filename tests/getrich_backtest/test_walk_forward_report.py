from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal

import polars as pl
import pytest

from getrich_backtest import (
    Backtest,
    BarContext,
    DataFrameBarLoader,
    GridSearch,
    P,
    ParamSpace,
    Side,
    Strategy,
    WalkForward,
    WalkForwardReport,
    WalkForwardRunSpec,
    get_shanghai_tz,
)
from getrich_backtest.strategy import OrderIntent


SYMBOL = "000001.SZ"


def _bars() -> pl.DataFrame:
    tz = get_shanghai_tz()
    dates = [
        datetime(2026, 1, 2, 9, 30, tzinfo=tz),
        datetime(2026, 1, 15, 9, 30, tzinfo=tz),
        datetime(2026, 2, 2, 9, 30, tzinfo=tz),
        datetime(2026, 2, 16, 9, 30, tzinfo=tz),
        datetime(2026, 3, 2, 9, 30, tzinfo=tz),
        datetime(2026, 3, 16, 9, 30, tzinfo=tz),
        datetime(2026, 4, 2, 9, 30, tzinfo=tz),
        datetime(2026, 4, 16, 9, 30, tzinfo=tz),
        datetime(2026, 5, 4, 9, 30, tzinfo=tz),
        datetime(2026, 5, 18, 9, 30, tzinfo=tz),
        datetime(2026, 6, 2, 9, 30, tzinfo=tz),
        datetime(2026, 6, 16, 9, 30, tzinfo=tz),
    ]
    closes = [Decimal(str(value)) for value in range(10, 22)]
    return pl.DataFrame(
        {
            "dt": dates,
            "symbol": [SYMBOL] * len(dates),
            "open": closes,
            "high": [close + Decimal("0.5") for close in closes],
            "low": [close - Decimal("0.5") for close in closes],
            "close": closes,
            "volume": [1000.0 + i for i in range(len(dates))],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


class BuyQtyStrategy(Strategy):
    def __init__(self, qty: Decimal) -> None:
        self.qty = qty
        self.calls = 0

    def on_bar(self, ctx: BarContext) -> Iterable[OrderIntent] | None:
        self.calls += 1
        if self.calls == 1:
            return [OrderIntent(symbol=SYMBOL, side=Side.BUY, qty=self.qty)]
        return None


def _search() -> GridSearch:
    return GridSearch(ParamSpace({"qty": P.categorical([Decimal("1"), Decimal("5")])}))


def _window_bounds() -> tuple[datetime, datetime]:
    tz = get_shanghai_tz()
    return datetime(2026, 1, 1, tzinfo=tz), datetime(2026, 7, 1, tzinfo=tz)


def _backtest(strategy: Strategy, spec: WalkForwardRunSpec) -> Backtest:
    start = spec.window.train_start if spec.phase == "train" else spec.window.val_start
    end = spec.window.train_end if spec.phase == "train" else spec.window.val_end
    return Backtest(
        strategy=strategy,
        bar_loader=DataFrameBarLoader(_bars()),
        symbols=[SYMBOL],
        start=start,
        end=end,
        initial_cash=Decimal("1000"),
        run_id=spec.run_id,
        strategy_params=spec.params,
    )


def _result() -> object:
    start, end = _window_bounds()
    wf = WalkForward(
        walk_forward_id="wf-report",
        search=_search(),
        train_months=2,
        val_months=1,
        step_months=2,
        select_metric="total_return",
    )
    return wf.run(
        start=start,
        end=end,
        strategy_factory=lambda params: BuyQtyStrategy(Decimal(str(params["qty"]))),
        backtest_factory=_backtest,
    )


def test_result_report_returns_walk_forward_report() -> None:
    report = _result().report()

    assert isinstance(report, WalkForwardReport)


def test_isoos_comparison_contains_metric_pairs_and_params() -> None:
    comparison = _result().report().isoos_comparison()

    assert comparison.height == 2
    assert "train_metric" in comparison.columns
    assert "validation_metric" in comparison.columns
    assert "metric_delta" in comparison.columns
    assert "drop_off_ratio" in comparison.columns
    assert "param_qty" in comparison.columns
    assert comparison["metric"].to_list() == ["total_return", "total_return"]


def test_window_metrics_frame_flattens_train_and_validation_metrics() -> None:
    frame = _result().report().window_metrics_frame()

    assert frame.height == 2
    assert "train_total_return" in frame.columns
    assert "validation_total_return" in frame.columns
    assert "best_run_id" in frame.columns
    assert "validation_run_id" in frame.columns


def test_best_params_per_window_returns_selected_params() -> None:
    frame = _result().report().best_params_per_window()

    assert frame.height == 2
    assert "best_params" in frame.columns
    assert "param_qty" in frame.columns
    assert frame["param_qty"].to_list() == [Decimal("5"), Decimal("5")]


def test_parameter_stability_aggregates_selected_params() -> None:
    frame = _result().report().parameter_stability("qty")

    assert frame.height == 1
    assert frame["param_qty"].to_list() == [Decimal("5")]
    assert frame["count"].to_list() == [2]
    assert "mean_validation_metric" in frame.columns


def test_parameter_stability_rejects_absent_param() -> None:
    with pytest.raises(ValueError, match="parameter not found"):
        _result().report().parameter_stability("missing")


def test_consistency_summary_reports_counts_and_metric() -> None:
    summary = _result().report().consistency_summary()

    assert summary["walk_forward_id"] == "wf-report"
    assert summary["metric"] == "total_return"
    assert summary["total_windows"] == 2
    assert summary["completed_windows"] == 2
    assert summary["failed_windows"] == 0
    assert isinstance(summary["mean_train_metric"], Decimal)
    assert isinstance(summary["mean_validation_metric"], Decimal)
    assert summary["rank_corr_is_oos"] is None or isinstance(summary["rank_corr_is_oos"], float)


def test_failed_windows_are_counted_but_excluded_from_frames() -> None:
    start, end = _window_bounds()
    wf = WalkForward(
        walk_forward_id="wf-report-fail",
        search=_search(),
        train_months=2,
        val_months=1,
        step_months=2,
        select_metric="total_return",
        fail_fast=False,
    )

    def backtest_factory(strategy: Strategy, spec: WalkForwardRunSpec) -> Backtest:
        if spec.phase == "validation" and spec.window.index == 0:
            raise RuntimeError("validation failed")
        return _backtest(strategy, spec)

    result = wf.run(
        start=start,
        end=end,
        strategy_factory=lambda params: BuyQtyStrategy(Decimal(str(params["qty"]))),
        backtest_factory=backtest_factory,
    )
    report = result.report()

    assert report.isoos_comparison().height == 1
    summary = report.consistency_summary()
    assert summary["total_windows"] == 2
    assert summary["completed_windows"] == 1
    assert summary["failed_windows"] == 1


def test_to_html_contains_expected_sections_and_plotly() -> None:
    html = _result().report().to_html()

    assert "<!DOCTYPE html>" in html
    assert "WalkForward Report" in html
    assert "wf-report" in html
    assert "OOS Equity Curve" in html
    assert "Train vs Validation Metric" in html
    assert "Selected Parameters" in html
    assert "IS/OOS Comparison" in html
    assert "plotly-graph-div" in html
    assert html.strip().endswith("</html>")


def test_public_api_exports_walk_forward_report() -> None:
    from getrich_backtest import WalkForwardReport as ExportedWalkForwardReport

    assert ExportedWalkForwardReport is WalkForwardReport
