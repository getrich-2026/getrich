"""Exception hierarchy for the GetRich backtesting framework."""

from __future__ import annotations


class BacktestError(Exception):
    """Base class for all backtest framework errors."""


class TimezoneError(BacktestError):
    """Raised when a datetime violates the framework timezone contract."""


class BarSchemaError(BacktestError):
    """Raised when bar data does not satisfy the canonical schema."""


class DataLoadError(BacktestError):
    """Raised when a bar loader cannot satisfy a load request."""


class ExecutionError(BacktestError):
    """Raised when the execution layer cannot process an order."""


class AccountError(BacktestError):
    """Raised when account state would violate a trading invariant."""


class StrategyError(BacktestError):
    """Raised for strategy API usage errors."""


class OrderIntentError(StrategyError):
    """Raised when an order intent is invalid."""


class MetricsError(BacktestError):
    """Raised when backtest metrics cannot be computed from the result data."""


class CorporateActionError(AccountError):
    """Raised when a corporate action cannot be applied to an account."""


class MarginError(AccountError):
    """Raised when margin requirements are not met."""


class RetryableError(BacktestError):
    """Op-level hint that an exception is safe to retry.

    The runner treats ``RetryableError`` the same as a plain
    ``Exception`` — i.e. honour ``max_attempts`` and call
    ``mark_retry`` for in-window failures. Subclassing
    ``RetryableError`` is purely documentation: it tells future readers
    "yes, retrying this is intended, and the op author thought about it."

    The actual opt-out-of-retry is :class:`TerminalError` (see below).
    """


class TerminalError(BacktestError):
    """Op-level signal that an exception should NOT be retried.

    When the runner sees a ``TerminalError`` (or any subclass) inside
    the op's ``except Exception`` block, it goes straight to
    ``mark_failed`` regardless of ``attempt < max_attempts``. This
    prevents wasting backoff cycles on permanent failures such as
    config validation errors, missing strategy code, or malformed
    request payloads.
    """
