"""Tests for ``SweepRunner.run(is_cancelled=...)`` cooperative cancellation."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal

import polars as pl

from getrich_backtest import (
    Backtest,
    BarContext,
    DataFrameBarLoader,
    GridSearch,
    P,
    ParamSpace,
    Side,
    Strategy,
    SweepRunner,
    get_shanghai_tz,
)
from getrich_backtest.strategy import OrderIntent


def _bars() -> pl.DataFrame:
    tz = get_shanghai_tz()
    return pl.DataFrame(
        {
            "dt": [
                datetime(2026, 1, 1, 9, 30, tzinfo=tz),
                datetime(2026, 1, 2, 9, 30, tzinfo=tz),
                datetime(2026, 1, 3, 9, 30, tzinfo=tz),
            ],
            "symbol": ["000001.SZ"] * 3,
            "open": [Decimal("10"), Decimal("11"), Decimal("12")],
            "high": [Decimal("10.5"), Decimal("11.5"), Decimal("12.5")],
            "low": [Decimal("9.5"), Decimal("10.5"), Decimal("11.5")],
            "close": [Decimal("10"), Decimal("11"), Decimal("12")],
            "volume": [1000.0, 1100.0, 1200.0],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


class _BuyQty(Strategy):
    def __init__(self, qty: int) -> None:
        self.qty = qty
        self.calls = 0

    def on_bar(self, ctx: BarContext) -> Iterable[OrderIntent] | None:
        self.calls += 1
        if self.calls == 1:
            return [OrderIntent(symbol="000001.SZ", side=Side.BUY, qty=Decimal(self.qty))]
        return None


def _backtest(strategy: Strategy, run_id: str, params: dict[str, object]) -> Backtest:
    tz = get_shanghai_tz()
    return Backtest(
        strategy=strategy,
        bar_loader=DataFrameBarLoader(_bars()),
        symbols=["000001.SZ"],
        start=datetime(2026, 1, 1, tzinfo=tz),
        end=datetime(2026, 1, 4, tzinfo=tz),
        initial_cash=Decimal("1000"),
        run_id=run_id,
        strategy_params=params,
    )


def test_sweep_runner_cancelled_false_by_default() -> None:
    runner = SweepRunner(
        sweep_id="s1",
        search=GridSearch(ParamSpace({"qty": P.categorical([1, 2])})),
    )
    result = runner.run(
        strategy_factory=lambda p: _BuyQty(int(p["qty"])),
        backtest_factory=lambda s, t: _backtest(s, t.run_id, t.params),
    )
    assert result.cancelled is False
    assert len(result.trials) == 2


def test_sweep_runner_breaks_when_is_cancelled_returns_true() -> None:
    """is_cancelled returning True at the start of trial N must stop the sweep."""
    runner = SweepRunner(
        sweep_id="s1",
        search=GridSearch(ParamSpace({"qty": P.categorical([1, 2, 3])})),
    )

    def _is_cancelled() -> bool:
        # The runner calls is_cancelled BEFORE each trial. The strategy
        # factory below advances the counter; on trial 2 the probe returns
        # True and the runner breaks out of the loop.
        return _is_cancelled.count > 0

    _is_cancelled.count = 0

    def _strategy_factory(p: dict[str, object]) -> Strategy:
        _is_cancelled.count += 1
        return _BuyQty(int(p["qty"]))

    result = runner.run(
        strategy_factory=_strategy_factory,
        backtest_factory=lambda s, t: _backtest(s, t.run_id, t.params),
        is_cancelled=_is_cancelled,
    )

    assert result.cancelled is True
    # First strategy factory call advances the counter; subsequent trials see
    # is_cancelled() return True and break.
    assert len(result.trials) == 1


def test_sweep_runner_swallows_is_cancelled_exceptions() -> None:
    """A misbehaving is_cancelled must not crash the engine."""

    def _boom() -> bool:
        raise RuntimeError("cancel probe blew up")

    runner = SweepRunner(
        sweep_id="s1",
        search=GridSearch(ParamSpace({"qty": P.categorical([1, 2])})),
    )
    result = runner.run(
        strategy_factory=lambda p: _BuyQty(int(p["qty"])),
        backtest_factory=lambda s, t: _backtest(s, t.run_id, t.params),
        is_cancelled=_boom,
    )

    assert result.cancelled is False
    assert len(result.trials) == 2


def test_sweep_runner_progress_still_fires_when_cancelled_mid_run() -> None:
    """is_cancelled and on_progress should coexist."""
    runner = SweepRunner(
        sweep_id="s1",
        search=GridSearch(ParamSpace({"qty": P.categorical([1, 2, 3])})),
    )
    progress_calls: list[tuple[int, int]] = []
    counter = {"n": 0}

    def _is_cancelled() -> bool:
        return counter["n"] > 0

    def _strategy_factory(p: dict[str, object]) -> Strategy:
        counter["n"] += 1
        return _BuyQty(int(p["qty"]))

    result = runner.run(
        strategy_factory=_strategy_factory,
        backtest_factory=lambda s, t: _backtest(s, t.run_id, t.params),
        on_progress=lambda done, total: progress_calls.append((done, total)),
        is_cancelled=_is_cancelled,
    )

    assert result.cancelled is True
    assert len(result.trials) == 1
    # The first trial emits one on_progress call before the second trial's
    # is_cancelled() returns True and breaks the loop.
    assert progress_calls == [(1, 3)]
