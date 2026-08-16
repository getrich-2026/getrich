"""Tests for ``gr_data.logging.Logger``.

The Logger class is a thin wrapper over :mod:`logging`'s
stdlib logger. It provides a stable per-module name and
the four canonical levels used throughout the codebase.

These tests are pure unit tests: they patch the standard
``logging.getLogger`` return-value and assert that the
wrapper dispatches to the right level.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from gr_data.logging import Logger


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


def test_logger_uses_provided_module_name() -> None:
    """`module_name` is forwarded verbatim to stdlib
    `logging.getLogger` — there is no name mangling."""
    fake_logger = MagicMock(spec=logging.Logger)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(logging, "getLogger", lambda name: fake_logger if name == "my.module" else None)

        log = Logger(module_name="my.module")

    assert log._logger is fake_logger


def test_logger_holds_logger_attribute() -> None:
    """`Logger._logger` stores the resolved stdlib logger so
    it can be introspected / patched by downstream code (the
    ClickHouse client reuses the same instance across calls)."""
    log = Logger(module_name="some.module")

    # The stdlib logger IS named "some.module" — no mangling.
    assert log._logger.name == "some.module"


# ---------------------------------------------------------------------------
# Level dispatch
# ---------------------------------------------------------------------------


def test_debug_dispatches_to_debug_level() -> None:
    """`Logger.debug(msg)` calls `_logger.debug(msg)`."""
    log = Logger(module_name="t")
    log._logger = MagicMock(spec=logging.Logger)

    log.debug("hello")

    log._logger.debug.assert_called_once_with("hello")


def test_info_dispatches_to_info_level() -> None:
    log = Logger(module_name="t")
    log._logger = MagicMock(spec=logging.Logger)

    log.info("hello")

    log._logger.info.assert_called_once_with("hello")


def test_warning_dispatches_to_warning_level() -> None:
    log = Logger(module_name="t")
    log._logger = MagicMock(spec=logging.Logger)

    log.warning("hello")

    log._logger.warning.assert_called_once_with("hello")


def test_error_dispatches_to_error_level() -> None:
    log = Logger(module_name="t")
    log._logger = MagicMock(spec=logging.Logger)

    log.error("hello")

    log._logger.error.assert_called_once_with("hello")


# ---------------------------------------------------------------------------
# Behavior with the real stdlib logger
# ---------------------------------------------------------------------------


def test_real_logger_does_not_raise() -> None:
    """End-to-end smoke test against the real stdlib logger
    — none of the four level methods raise. We don't assert
    on output (logging is configured globally)."""
    log = Logger(module_name="getrich.test_logging.smoke")

    log.debug("debug message")
    log.info("info message")
    log.warning("warning message")
    log.error("error message")


def test_logger_is_independent_per_module_name() -> None:
    """Two `Logger` instances with different module names
    resolve to different stdlib loggers (stdlib behavior:
    `logging.getLogger` is idempotent on the same name, but
    two distinct names yield distinct instances)."""
    a = Logger(module_name="module.a")
    b = Logger(module_name="module.b")

    assert a._logger is not b._logger
    assert a._logger.name == "module.a"
    assert b._logger.name == "module.b"
