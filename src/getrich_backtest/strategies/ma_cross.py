"""Moving average crossover strategy.

Buys when the fast SMA crosses above the slow SMA, and closes the
position when the fast SMA crosses below the slow SMA.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

import polars as pl

from getrich_backtest.indicators import sma
from getrich_backtest.strategy.base import Strategy
from getrich_backtest.strategy.context import BarContext
from getrich_backtest.strategy.order import OrderIntent
from getrich_backtest.types import Side


class MACross(Strategy):
    """Moving average crossover strategy.

    Parameters
    ----------
    fast : int
        Fast SMA period (default 10).
    slow : int
        Slow SMA period (default 30).
    """

    def __init__(self, fast: int = 10, slow: int = 30) -> None:
        if fast >= slow:
            raise ValueError("fast period must be less than slow period")
        self.fast = fast
        self.slow = slow
        self._has_position = False

    def on_bar(self, ctx: BarContext) -> Iterable[OrderIntent] | None:
        # Get enough history for both SMAs (slow + 1 so previous SMA is valid)
        history = ctx.lookback(n=self.slow + 1, columns=["dt", "symbol", "close"])
        if history.is_empty() or history.height < 2:
            return None

        history = sma(history, self.fast)
        history = sma(history, self.slow)

        # Get the last two rows for crossover detection
        last_two = history.with_columns(pl.all().shift(1).name.suffix("_prev")).tail(1)
        if last_two.is_empty():
            return None

        row = last_two.row(0, named=True)
        fast_now = row.get(f"sma_{self.fast}")
        slow_now = row.get(f"sma_{self.slow}")
        fast_prev = row.get(f"sma_{self.fast}_prev")
        slow_prev = row.get(f"sma_{self.slow}_prev")

        if None in (fast_now, slow_now, fast_prev, slow_prev):
            return None

        # Crossover up: fast > slow now, but was not before
        if fast_now > slow_now and fast_prev <= slow_prev and not self._has_position:
            self._has_position = True
            return [OrderIntent(symbol="000001.SZ", side=Side.BUY, weight=Decimal("1.0"))]

        # Crossover down: fast < slow now, but was not before
        if fast_now < slow_now and fast_prev >= slow_prev and self._has_position:
            self._has_position = False
            return [OrderIntent(symbol="000001.SZ", side=Side.SELL, weight=Decimal("1.0"))]

        return None
