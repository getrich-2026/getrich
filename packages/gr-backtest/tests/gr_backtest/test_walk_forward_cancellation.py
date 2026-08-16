"""Tests for ``WalkForward.run(is_cancelled=...)`` cooperative cancellation."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal

import polars as pl
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


class _BuyQty(Strategy):
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


def test_walk_forward_cancelled_false_by_default() -> None:
    tz = get_shanghai_tz()
    wf = WalkForward(
        walk_forward_id="wf",
        search=_search(),
        train_months=2,
        val_months=1,
        step_months=1,
    )
    result = wf.run(
        start=datetime(2026, 1, 1, tzinfo=tz),
        end=datetime(2026, 7, 1, tzinfo=tz),
        strategy_factory=lambda p: _BuyQty(p["qty"]),
        backtest_factory=_backtest,
    )
    assert result.cancelled is False
    assert len(result.windows) == 4


def test_walk_forward_breaks_when_is_cancelled_returns_true() -> None:
    tz = get_shanghai_tz()
    wf = WalkForward(
        walk_forward_id="wf",
        search=_search(),
        train_months=2,
        val_months=1,
        step_months=1,
    )
    counter = {"n": 0}

    def _is_cancelled() -> bool:
        return counter["n"] > 0

    def _strategy_factory(p: dict[str, object]) -> Strategy:
        counter["n"] += 1
        return _BuyQty(p["qty"])

    result = wf.run(
        start=datetime(2026, 1, 1, tzinfo=tz),
        end=datetime(2026, 7, 1, tzinfo=tz),
        strategy_factory=_strategy_factory,
        backtest_factory=_backtest,
        is_cancelled=_is_cancelled,
    )

    assert result.cancelled is True
    # First window consumes one strategy_factory call (counter goes to 1);
    # subsequent windows see is_cancelled() return True and break.
    assert len(result.windows) == 1


def test_walk_forward_swallows_is_cancelled_exceptions() -> None:
    tz = get_shanghai_tz()
    wf = WalkForward(
        walk_forward_id="wf",
        search=_search(),
        train_months=2,
        val_months=1,
        step_months=1,
    )

    def _boom() -> bool:
        raise RuntimeError("cancel probe blew up")

    result = wf.run(
        start=datetime(2026, 1, 1, tzinfo=tz),
        end=datetime(2026, 7, 1, tzinfo=tz),
        strategy_factory=lambda p: _BuyQty(p["qty"]),
        backtest_factory=_backtest,
        is_cancelled=_boom,
    )

    assert result.cancelled is False
    assert len(result.windows) == 4
