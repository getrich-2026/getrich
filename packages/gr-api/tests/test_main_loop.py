"""Regression test for Round #1204 (Tier 1): Windows ProactorEventLoop fix.

The web app's ``main.py`` and the worker's ``tasks.py`` / ``lifespan.py``
force ``SelectorEventLoop`` on Windows at import time. Without it, the
first ``await pg_pool.init()`` (or any other async psycopg3 call)
explodes with::

    Psycopg cannot use the 'ProactorEventLoop' to run in async mode.
    Please use a compatible event loop, for instance by running
    'asyncio.run(..., loop_factory=asyncio.SelectorEventLoop(
        selectors.SelectSelector()))'

This test does NOT touch the DB — it only verifies the import-time
side-effect (the event loop policy switch). That way it runs in CI
without docker / pg services.
"""

from __future__ import annotations

import asyncio
import sys

import pytest


# Importing the module must not raise. We import inside the test body
# so the side-effect (set_event_loop_policy) actually runs in the
# test process — pytest's import order otherwise might re-order
# things.
def test_web_main_imports_without_error() -> None:
    """Smoke test: importing ``gr_api.main`` must not raise.

    Pre-Round-#1204, this module imported without error too, so
    the test mostly guards against typos in the new ``import sys``
    / ``set_event_loop_policy`` block. The actual policy assertion
    is in the next test.
    """
    import gr_api.main  # noqa: F401


def test_worker_tasks_imports_without_error() -> None:
    """Same smoke for the worker entry point."""
    import gr_api.worker.tasks  # noqa: F401


def test_worker_lifespan_imports_without_error() -> None:
    """Same smoke for the worker lifespan helpers."""
    import gr_api.worker.lifespan  # noqa: F401


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows-only ProactorEventLoop guard; POSIX is unaffected",
)
def test_windows_event_loop_policy_is_selector() -> None:
    """On Windows the active policy must be WindowsSelectorEventLoopPolicy.

    We re-assert after a fresh import: pytest's conftest may install
    a different policy between module imports.
    """
    # Force the import side-effect to run (idempotent).
    import gr_api.main  # noqa: F401
    import gr_api.worker.lifespan  # noqa: F401
    import gr_api.worker.tasks  # noqa: F401

    policy = asyncio.get_event_loop_policy()
    assert isinstance(policy, asyncio.WindowsSelectorEventLoopPolicy), (
        f"Expected WindowsSelectorEventLoopPolicy after imports, "
        f"got {type(policy).__name__}. The Round #1204 fix in main.py / "
        f"tasks.py / lifespan.py must have been reverted."
    )


def test_event_loop_policy_unchanged_on_posix() -> None:
    """On POSIX, the policy must NOT be touched — Linux + macOS use
    SelectorEventLoop by default and we don't want to install any
    non-default policy. This is the "do no harm" half of the fix.
    """
    if sys.platform == "win32":
        pytest.skip("POSIX check; Windows has its own policy assertion")

    # The current policy on POSIX is whatever Python shipped with
    # (typically a SelectorEventLoopPolicy subclass). The test just
    # confirms that none of our import side-effects CHANGED it to
    # something exotic (e.g. a custom subclass with overridden
    # loop factory that doesn't work with psycopg3).
    import gr_api.main  # noqa: F401
    import gr_api.worker.lifespan  # noqa: F401
    import gr_api.worker.tasks  # noqa: F401

    policy = asyncio.get_event_loop_policy()
    # POSIX default is ``DefaultEventLoopPolicy`` which is the
    # SelectorEventLoopFactory on Linux/macOS. Whatever it is, it
    # must NOT be a custom user-installed override.
    assert policy is asyncio.DefaultEventLoopPolicy() or isinstance(
        policy, asyncio.DefaultEventLoopPolicy
    ), (
        f"Expected default asyncio policy on POSIX, got {type(policy).__name__}. "
        f"Round #1204 fix should be a no-op on non-Windows platforms."
    )
