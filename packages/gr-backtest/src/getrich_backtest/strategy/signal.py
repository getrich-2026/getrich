"""Signal-based strategy abstraction.

``SignalStrategy`` lets users express factor signals by overriding
``compute_signal()``.  A ``Portfolio`` member converts scores to
``OrderIntent`` objects automatically.
"""

from __future__ import annotations

from collections.abc import Iterable

import polars as pl

from getrich_backtest.exceptions import StrategyError
from getrich_backtest.strategy.base import Strategy
from getrich_backtest.strategy.context import BarContext
from getrich_backtest.strategy.order import OrderIntent
from getrich_backtest.strategy.portfolio import Portfolio


class SignalStrategy(Strategy):
    """Strategy that expresses factor signals via ``compute_signal()``.

    Override ``compute_signal()`` to return a ``[symbol, score]`` DataFrame.
    The base ``on_bar()`` delegates to the configured ``portfolio`` to
    convert scores into ``OrderIntent`` objects.

    Examples
    --------
    >>> class Momentum(SignalStrategy):
    ...     portfolio = Portfolio(EqualWeight(top_k=5, long_only=True))
    ...     def compute_signal(self, ctx):
    ...         hist = ctx.lookback(columns=["close"], n=21)
    ...         return hist.group_by("symbol").agg(
    ...             score=pl.col("close").last() / pl.col("close").first()
    ...         )
    """

    portfolio: Portfolio | None = None

    def compute_signal(self, ctx: BarContext) -> pl.DataFrame:
        """Return a ``[symbol, score]`` DataFrame.

        Override this method in your subclass.
        """
        raise NotImplementedError(f"{type(self).__name__} must implement compute_signal()")

    def on_bar(self, ctx: BarContext) -> Iterable[OrderIntent] | None:
        if self.portfolio is None:
            raise StrategyError(
                f"{type(self).__name__} requires a Portfolio instance; set self.portfolio"
            )
        scores = self.compute_signal(ctx)
        if scores is None or scores.is_empty():
            return None
        return self.portfolio.build_orders(scores, ctx)
