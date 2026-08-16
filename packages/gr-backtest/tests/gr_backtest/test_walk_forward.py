from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal

import polars as pl
import pytest
from gr_backtest import (
    Backtest,
    BarContext,
    DataFrameBarLoader,
    GridSearch,
    P,
    ParamSpace,
    Side,
    Strategy,
    WalkForward,
    WalkForwardRunSpec,
    get_shanghai_tz,
)
from gr_backtest.strategy import OrderIntent


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


def test_rolling_window_generation_uses_half_open_months() -> None:
    start, end = _window_bounds()
    wf = WalkForward(
        walk_forward_id="wf-roll",
        search=_search(),
        train_months=2,
        val_months=1,
        step_months=1,
    )

    windows = list(wf.iter_windows(start=start, end=end))

    month_ranges = [
        (w.train_start.month, w.train_end.month, w.val_start.month, w.val_end.month)
        for w in windows
    ]
    assert month_ranges == [
        (1, 3, 3, 4),
        (2, 4, 4, 5),
        (3, 5, 5, 6),
        (4, 6, 6, 7),
    ]
    assert [w.index for w in windows] == [0, 1, 2, 3]


def test_anchored_window_generation_expands_train_end() -> None:
    start, end = _window_bounds()
    wf = WalkForward(
        walk_forward_id="wf-anchor",
        search=_search(),
        train_months=2,
        val_months=1,
        step_months=1,
        refit="anchored",
    )

    windows = list(wf.iter_windows(start=start, end=end))

    month_ranges = [
        (w.train_start.month, w.train_end.month, w.val_start.month, w.val_end.month)
        for w in windows
    ]
    assert month_ranges == [
        (1, 3, 3, 4),
        (1, 4, 4, 5),
        (1, 5, 5, 6),
        (1, 6, 6, 7),
    ]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"walk_forward_id": ""}, "walk_forward_id must be non-empty"),
        ({"train_months": 0}, "train_months must be positive"),
        ({"val_months": 0}, "val_months must be positive"),
        ({"step_months": 0}, "step_months must be positive"),
        ({"refit": "expanding"}, "refit must be"),
    ],
)
def test_invalid_config_validation(kwargs: dict[str, object], message: str) -> None:
    params = {
        "walk_forward_id": "wf-invalid",
        "search": _search(),
        "train_months": 2,
        "val_months": 1,
    }
    params.update(kwargs)

    with pytest.raises(ValueError, match=message):
        WalkForward(**params)  # type: ignore[arg-type]


def test_iter_windows_rejects_invalid_range() -> None:
    start, _ = _window_bounds()
    wf = WalkForward(
        walk_forward_id="wf-range",
        search=_search(),
        train_months=2,
        val_months=1,
    )

    with pytest.raises(Exception, match="start must be earlier than end"):
        list(wf.iter_windows(start=start, end=start))


def test_runner_orchestrates_train_sweeps_and_validation_with_fresh_strategies() -> None:
    start, end = _window_bounds()
    created: list[BuyQtyStrategy] = []
    specs: list[WalkForwardRunSpec] = []
    wf = WalkForward(
        walk_forward_id="wf-run",
        search=_search(),
        train_months=2,
        val_months=1,
        step_months=2,
        select_metric="total_return",
    )

    def strategy_factory(params: dict[str, object]) -> Strategy:
        strategy = BuyQtyStrategy(Decimal(str(params["qty"])))
        created.append(strategy)
        return strategy

    def backtest_factory(strategy: Strategy, spec: WalkForwardRunSpec) -> Backtest:
        specs.append(spec)
        return _backtest(strategy, spec)

    result = wf.run(
        start=start,
        end=end,
        strategy_factory=strategy_factory,
        backtest_factory=backtest_factory,
    )

    assert len(result.completed()) == 2
    assert result.failed() == ()
    assert [spec.phase for spec in specs] == [
        "train",
        "train",
        "validation",
        "train",
        "train",
        "validation",
    ]
    assert len({id(strategy) for strategy in created}) == 6
    for window_result in result.completed():
        assert window_result.best_trial is not None
        assert window_result.best_trial.trial.params == {"qty": Decimal("5")}
        assert window_result.validation_result is not None
        assert window_result.validation_result.config.strategy_params == {"qty": Decimal("5")}
        assert window_result.validation_result.run_id.startswith("wf-run-w")
        assert "validation" in window_result.validation_result.run_id


def test_failure_handling_records_failed_window_and_continues() -> None:
    start, end = _window_bounds()
    wf = WalkForward(
        walk_forward_id="wf-fail",
        search=_search(),
        train_months=2,
        val_months=1,
        step_months=2,
        select_metric="total_return",
        fail_fast=False,
    )

    def strategy_factory(params: dict[str, object]) -> Strategy:
        return BuyQtyStrategy(Decimal(str(params["qty"])))

    def backtest_factory(strategy: Strategy, spec: WalkForwardRunSpec) -> Backtest:
        if spec.phase == "validation" and spec.window.index == 0:
            raise RuntimeError("validation failed")
        return _backtest(strategy, spec)

    result = wf.run(
        start=start,
        end=end,
        strategy_factory=strategy_factory,
        backtest_factory=backtest_factory,
    )

    assert len(result.windows) == 2
    assert len(result.failed()) == 1
    assert len(result.completed()) == 1
    assert result.failed()[0].error_message == "validation failed"
    assert result.completed()[0].window.index == 1


def test_failure_handling_reraises_when_fail_fast() -> None:
    start, end = _window_bounds()
    wf = WalkForward(
        walk_forward_id="wf-fast",
        search=_search(),
        train_months=2,
        val_months=1,
        select_metric="total_return",
        fail_fast=True,
    )

    with pytest.raises(RuntimeError, match="boom"):
        wf.run(
            start=start,
            end=end,
            strategy_factory=lambda params: BuyQtyStrategy(Decimal(str(params["qty"]))),
            backtest_factory=lambda strategy, spec: (_ for _ in ()).throw(RuntimeError("boom")),
        )


def test_result_helpers_flatten_windows_and_oos_equity() -> None:
    start, end = _window_bounds()
    wf = WalkForward(
        walk_forward_id="wf-helpers",
        search=_search(),
        train_months=2,
        val_months=1,
        step_months=2,
        select_metric="total_return",
    )

    result = wf.run(
        start=start,
        end=end,
        strategy_factory=lambda params: BuyQtyStrategy(Decimal(str(params["qty"]))),
        backtest_factory=_backtest,
    )

    summary = result.summary()
    assert summary["total_windows"] == 2
    assert summary["completed_windows"] == 2
    assert summary["failed_windows"] == 0
    assert isinstance(summary["mean_validation_metric"], Decimal)

    frame = result.to_frame()
    assert frame.height == 2
    assert "param_qty" in frame.columns
    assert "validation_total_return" in frame.columns
    assert frame["status"].to_list() == ["completed", "completed"]

    equity = result.oos_equity_curve()
    assert equity.height > 0
    assert "window_index" in equity.columns
    assert "run_id" in equity.columns
    assert set(equity["window_index"].to_list()) == {0, 1}
