"""Base strategy API."""

from __future__ import annotations

from collections.abc import Iterable

from gr_backtest.strategy.context import BarContext, Context
from gr_backtest.strategy.order import OrderIntent


class Strategy:
    """Base class for user-defined backtest strategies.

    Class Attributes
    ----------------
    freq : str | None
        Bar frequency the strategy expects.  When ``None`` (default) the
        strategy inherits the backtestʼs primary frequency.  Set to a valid
        :class:`~gr_backtest.types.Frequency` value (e.g. ``"5m"``,
        ``"1d"``) to have the engine call :meth:`on_bar` only at that
        frequencyʼs bar boundaries, even when other strategies in the same
        multi-strategy backtest run at different frequencies.
    """

    version = "0.1.0"
    freq: str | None = None

    @property
    def name(self) -> str:
        """Return the strategy name."""
        return self.__class__.__name__

    def setup(self, ctx: Context) -> None:
        """Run once before the strategy receives bars."""

    def teardown(self, ctx: Context) -> None:
        """Run once after the strategy finishes."""

    def on_bar(self, ctx: BarContext) -> Iterable[OrderIntent] | None:
        """Handle one visible bar window."""
        return None
