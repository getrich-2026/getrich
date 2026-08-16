"""Exception hierarchy for the LiveSignal module."""

from gr_backtest.exceptions import StrategyError


class LiveSignalError(StrategyError):
    """Base exception for LiveSignal module."""


class SignalProductionError(LiveSignalError):
    """Raised when signal production fails."""
