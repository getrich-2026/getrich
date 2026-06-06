"""Tests for the P2 #314 exception hierarchy additions: ``RetryableError``
and ``TerminalError``.

These tests validate:

* Both new classes inherit from ``BacktestError`` so existing
  ``except BacktestError:`` handlers keep working.
* Both new classes are publicly exported from ``getrich_backtest``.
* ``RetryableError`` and ``TerminalError`` are siblings under
  ``BacktestError`` (not a subclass of each other).
* ``getrich.apps.strategy.errors.BacktestJobError`` multi-inherits from
  ``TerminalError`` so the existing validation sites in
  ``apps/strategy/ops.py`` are picked up by the runner's
  ``isinstance(exc, TerminalError)`` short-circuit.
* The persistence-layer ``BacktestJobError`` (``getrich_backtest.job_persistence``)
  is NOT a ``TerminalError`` (they share a name by historical accident;
  the persistence one is for DB-layer errors that the runner does not
  catch).
"""

from __future__ import annotations


def test_retryable_error_inherits_from_backtest_error() -> None:
    from getrich_backtest import BacktestError, RetryableError

    err = RetryableError("db blip")
    assert isinstance(err, BacktestError)
    assert isinstance(err, Exception)


def test_terminal_error_inherits_from_backtest_error() -> None:
    from getrich_backtest import BacktestError, TerminalError

    err = TerminalError("bad config")
    assert isinstance(err, BacktestError)
    assert isinstance(err, Exception)


def test_retryable_error_is_not_a_terminal_error() -> None:
    """The two classes are siblings, not parent/child."""
    from getrich_backtest import RetryableError, TerminalError

    err = RetryableError("transient")
    assert not isinstance(err, TerminalError)


def test_terminal_error_is_not_a_retryable_error() -> None:
    """Symmetric to the above."""
    from getrich_backtest import RetryableError, TerminalError

    err = TerminalError("permanent")
    assert not isinstance(err, RetryableError)


def test_retryable_and_terminal_are_exported_from_package_root() -> None:
    """``from getrich_backtest import RetryableError, TerminalError`` works."""
    import getrich_backtest

    assert "RetryableError" in getrich_backtest.__all__
    assert "TerminalError" in getrich_backtest.__all__
    # And they resolve to the same classes we'd import from exceptions.
    from getrich_backtest.exceptions import (
        RetryableError as _Retryable,
        TerminalError as _Terminal,
    )

    assert getrich_backtest.RetryableError is _Retryable
    assert getrich_backtest.TerminalError is _Terminal


def test_backtest_job_error_is_a_terminal_error_via_multiple_inheritance() -> None:
    """``getrich.apps.strategy.errors.BacktestJobError`` is the canonical
    error raised by ``apps/strategy/ops.py`` validation sites. It now
    multi-inherits from ``TerminalError`` so the runner's
    ``isinstance(exc, TerminalError)`` check fires for them."""
    from getrich.apps.strategy.errors import BacktestJobError, StrategyEngineError
    from getrich_backtest import TerminalError

    err = BacktestJobError("search_spec.space must be a non-empty dict")
    assert isinstance(err, TerminalError)
    assert isinstance(err, StrategyEngineError)
    # MRO sanity: the TerminalError comes after StrategyEngineError so
    # existing ``except StrategyEngineError:`` handlers still catch it.
    mro = type(err).__mro__
    assert mro.index(StrategyEngineError) < mro.index(TerminalError)


def test_persistence_layer_backtest_job_error_is_not_a_terminal_error() -> None:
    """The two ``BacktestJobError`` classes share a name but are
    unrelated. The persistence-layer one is a DB-error wrapper, not an
    op error, and must NOT be picked up by the runner's TerminalError
    branch (the runner doesn't catch it anyway, but the explicit
    non-relationship guards against future import confusion)."""
    from getrich_backtest.exceptions import TerminalError
    from getrich_backtest.job_persistence import BacktestJobError as PersistenceBJE

    err = PersistenceBJE("connection refused")
    assert not isinstance(err, TerminalError)
