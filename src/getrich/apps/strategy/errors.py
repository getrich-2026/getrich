"""Exception hierarchy for the strategy engine."""

from getrich_backtest.exceptions import TerminalError


class StrategyEngineError(Exception):
    """Base exception for the strategy engine module."""


class SignalWriteError(StrategyEngineError):
    """Raised when a signal cannot be written to the database."""


class LiveDataError(StrategyEngineError):
    """Raised when live market data cannot be loaded or normalized."""


class LiveRunnerError(StrategyEngineError):
    """Raised when live signal orchestration fails fatally."""


class StrategyRegistryError(StrategyEngineError):
    """Raised when strategy lookup or instantiation fails."""


class BacktestJobError(StrategyEngineError, TerminalError):
    """Raised when a backtest job cannot be created, claimed, or run.

    Also a :class:`TerminalError` — these are validation / config failures
    that retrying cannot fix. The ``BacktestJobRunner`` skips the retry
    path and goes straight to ``mark_failed`` when one of these is
    raised from an op, regardless of ``max_attempts``.
    """
