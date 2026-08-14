"""Tests for ``WalkForward.run(on_progress=...)`` per-window progress hook."""

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
    WalkForward,
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


def test_walk_forward_invokes_on_progress_per_window() -> None:
    """on_progress should fire once per window (after train+val)."""
    tz = get_shanghai_tz()
    wf = WalkForward(
        walk_forward_id="wf-roll",
        search=_search(),
        train_months=2,
        val_months=1,
        step_months=1,
    )
    calls: list[tuple[int, int]] = []

    result = wf.run(
        start=datetime(2026, 1, 1, tzinfo=tz),
        end=datetime(2026, 7, 1, tzinfo=tz),
        strategy_factory=lambda p: _BuyQty(p["qty"]),
        backtest_factory=_backtest,
        on_progress=lambda done, total: calls.append((done, total)),
    )

    # 4 windows × (train+val) — on_progress counts completed windows.
    assert calls == [(1, 4), (2, 4), (3, 4), (4, 4)]
    assert len(result.windows) == 4


def test_walk_forward_without_on_progress_behaves_unchanged() -> None:
    tz = get_shanghai_tz()
    wf = WalkForward(
        walk_forward_id="wf-roll",
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
    assert len(result.windows) == 4


def test_walk_forward_swallows_on_progress_exceptions() -> None:
    tz = get_shanghai_tz()
    wf = WalkForward(
        walk_forward_id="wf-roll",
        search=_search(),
        train_months=2,
        val_months=1,
        step_months=1,
    )

    def _boom(done: int, total: int) -> None:
        raise RuntimeError("progress callback blew up")

    result = wf.run(
        start=datetime(2026, 1, 1, tzinfo=tz),
        end=datetime(2026, 7, 1, tzinfo=tz),
        strategy_factory=lambda p: _BuyQty(p["qty"]),
        backtest_factory=_backtest,
        on_progress=_boom,
    )

    assert len(result.windows) == 4
    assert all(w.status == "completed" for w in result.windows)
