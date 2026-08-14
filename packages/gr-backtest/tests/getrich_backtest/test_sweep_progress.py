"""Tests for ``SweepRunner.run(on_progress=...)`` per-trial progress hook."""

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
            "symbol": ["000001.SZ", "000001.SZ", "000001.SZ"],
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


def test_sweep_runner_invokes_on_progress_per_trial() -> None:
    """on_progress should fire once per trial, ending at (total, total)."""
    runner = SweepRunner(
        sweep_id="s1",
        search=GridSearch(ParamSpace({"qty": P.categorical([1, 2, 3])})),
    )
    calls: list[tuple[int, int]] = []

    result = runner.run(
        strategy_factory=lambda p: _BuyQty(int(p["qty"])),
        backtest_factory=lambda s, t: _backtest(s, t.run_id, t.params),
        on_progress=lambda done, total: calls.append((done, total)),
    )

    assert calls == [(1, 3), (2, 3), (3, 3)]
    assert len(result.trials) == 3


def test_sweep_runner_without_on_progress_behaves_unchanged() -> None:
    """Omitting on_progress keeps the legacy behaviour (no error)."""
    runner = SweepRunner(
        sweep_id="s1",
        search=GridSearch(ParamSpace({"qty": P.categorical([1, 2])})),
    )
    result = runner.run(
        strategy_factory=lambda p: _BuyQty(int(p["qty"])),
        backtest_factory=lambda s, t: _backtest(s, t.run_id, t.params),
    )
    assert len(result.trials) == 2


def test_sweep_runner_swallows_on_progress_exceptions() -> None:
    """A misbehaving progress callback must not break the sweep loop."""

    def _boom(done: int, total: int) -> None:
        raise RuntimeError("progress callback blew up")

    runner = SweepRunner(
        sweep_id="s1",
        search=GridSearch(ParamSpace({"qty": P.categorical([1, 2])})),
    )
    result = runner.run(
        strategy_factory=lambda p: _BuyQty(int(p["qty"])),
        backtest_factory=lambda s, t: _backtest(s, t.run_id, t.params),
        on_progress=_boom,
    )

    assert len(result.trials) == 2
    assert all(t.status == "completed" for t in result.trials)


def test_sweep_runner_progress_fires_even_when_trial_fails() -> None:
    """Failed trials should still count toward progress (the engine moves on)."""
    runner = SweepRunner(
        sweep_id="s1",
        search=GridSearch(ParamSpace({"qty": P.categorical([1, 2])})),
        fail_fast=False,
    )
    calls: list[tuple[int, int]] = []

    def _factory(_params: dict[str, object]) -> Strategy:
        raise RuntimeError("factory error")

    result = runner.run(
        strategy_factory=_factory,
        backtest_factory=lambda s, t: _backtest(s, t.run_id, t.params),
        on_progress=lambda done, total: calls.append((done, total)),
    )

    assert calls == [(1, 2), (2, 2)]
    assert all(t.status == "failed" for t in result.trials)
