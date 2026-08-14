"""Bollinger Bands mean reversion strategy.

Buys when the close price touches or crosses below the lower band,
and sells (closes long) when the close price touches or crosses
above the upper band.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from getrich_backtest.indicators import bollinger
from getrich_backtest.strategy.base import Strategy
from getrich_backtest.strategy.context import BarContext
from getrich_backtest.strategy.order import OrderIntent
from getrich_backtest.types import Side


class BollingerMeanReversion(Strategy):
    """Bollinger Bands mean reversion strategy.

    Parameters
    ----------
    period : int
        Bollinger Bands SMA period (default 20).
    std : int
        Number of standard deviations for the bands (default 2).
    """

    def __init__(self, period: int = 20, std: int = 2) -> None:
        self.period = period
        self.std = std
        self._has_position = False

    def on_bar(self, ctx: BarContext) -> Iterable[OrderIntent] | None:
        history = ctx.lookback(n=self.period, columns=["dt", "symbol", "close"])
        if history.is_empty() or history.height < self.period:
            return None

        history = bollinger(history, period=self.period, std=self.std)
        last = history.tail(1).row(0, named=True)

        close = last.get("close")
        lower = last.get("bb_lower")
        upper = last.get("bb_upper")

        if close is None or lower is None or upper is None:
            return None

        # Close below lower band → buy (oversold)
        if close <= lower and not self._has_position:
            self._has_position = True
            return [OrderIntent(symbol="000001.SZ", side=Side.BUY, weight=Decimal("1.0"))]

        # Close above upper band → sell (overbought)
        if close >= upper and self._has_position:
            self._has_position = False
            return [OrderIntent(symbol="000001.SZ", side=Side.SELL, weight=Decimal("1.0"))]

        return None
