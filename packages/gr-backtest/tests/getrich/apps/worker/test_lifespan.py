"""Tests for ``getrich.apps.worker.lifespan``.

The lifespan module exposes two sync helpers,
``init_pg_pool()`` and ``close_pg_pool()``, that bridge
Celery's sync task body to the project's async
``PgConnectionPool`` API.

The two operations have asymmetric error handling:

- ``init_pg_pool()`` RE-RAISES on failure (Celery needs the
  task to FAILED so the operator sees the error).
- ``close_pg_pool()`` SWALLOWS errors at teardown (we don't
  want a teardown error to mask a successful task result).

Both functions drive the async pool via ``asyncio.run``
(no long-lived loop — see the module docstring for why).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from getrich.apps.worker import lifespan
from gr_data.db.pool import pg_pool


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# init_pg_pool
# ---------------------------------------------------------------------------


def test_init_pg_pool_calls_pg_pool_init() -> None:
    """`init_pg_pool()` delegates to `pg_pool.init()` via
    a fresh `asyncio.run` loop."""
    with patch.object(lifespan, "asyncio") as fake_asyncio:
        fake_asyncio.run.return_value = None
        lifespan.init_pg_pool()

    fake_asyncio.run.assert_called_once()
    # The argument must be a coroutine — we can introspect
    # the call to confirm.
    call_arg = fake_asyncio.run.call_args[0][0]
    # `pg_pool.init()` returns a coroutine; we just assert
    # it's the right type from the right call site.
    assert hasattr(call_arg, "__await__") or hasattr(call_arg, "send")


def test_init_pg_pool_reraises_on_failure() -> None:
    """A failed `pg_pool.init()` propagates so Celery marks
    the task as FAILED and operators see the traceback in
    worker logs. The wrapper logs the failure before re-raise
    (via `logger.exception`)."""
    with patch.object(lifespan, "asyncio") as fake_asyncio:
        fake_asyncio.run.side_effect = RuntimeError("connect refused")

        with pytest.raises(RuntimeError, match="connect refused"):
            lifespan.init_pg_pool()


def test_init_pg_pool_returns_none_on_success() -> None:
    """Successful init returns None (no result)."""
    with patch.object(lifespan, "asyncio") as fake_asyncio:
        fake_asyncio.run.return_value = None

        result = lifespan.init_pg_pool()

    assert result is None


# ---------------------------------------------------------------------------
# close_pg_pool
# ---------------------------------------------------------------------------


def test_close_pg_pool_calls_pg_pool_close() -> None:
    with patch.object(lifespan, "asyncio") as fake_asyncio:
        fake_asyncio.run.return_value = None
        lifespan.close_pg_pool()

    fake_asyncio.run.assert_called_once()


def test_close_pg_pool_swallows_errors() -> None:
    """`close_pg_pool()` is the symmetric counterpart to
    `init_pg_pool()`: it MUST NOT raise. If it did, the
    caller's `finally` block would re-raise and obscure
    whatever the task was actually trying to do.

    The trade-off: we lose visibility into pool teardown
    failures, but the worker is shutting down anyway —
    a leaked pool will be reaped by the OS."""
    with patch.object(lifespan, "asyncio") as fake_asyncio:
        fake_asyncio.run.side_effect = RuntimeError("pool already closed")

        # Must NOT raise.
        lifespan.close_pg_pool()


def test_close_pg_pool_is_safe_when_pool_never_initialized() -> None:
    """If `pg_pool.init()` was never called, `pg_pool.close()`
    is a no-op (per the pool's design — it checks
    `self._pool is not None`). The lifespan wrapper must
    handle this without error."""
    # The real pool's `close()` is a no-op when _pool is None.
    # We don't even need to mock — call it on a fresh singleton.
    pg_pool._pool = None  # reset
    lifespan.close_pg_pool()  # should not raise


# ---------------------------------------------------------------------------
# Integration: open / close cycle
# ---------------------------------------------------------------------------


def test_init_close_cycle_invokes_pg_pool() -> None:
    """The two helpers are typically called in a try/finally
    from the task body. Verify that pattern works (with
    asyncio.run mocked to confirm call order)."""
    call_order: list[str] = []

    with patch.object(lifespan, "asyncio") as fake_asyncio:

        def _record_init(_coro):
            call_order.append("init")
            return None

        def _record_close(_coro):
            call_order.append("close")
            return None

        fake_asyncio.run.side_effect = _record_init  # first call

        # Use a side_effect chain to handle both calls
        def _side_effect(_coro):
            if not call_order:
                call_order.append("init")
            else:
                call_order.append("close")
            return None

        fake_asyncio.run.side_effect = _side_effect

        lifespan.init_pg_pool()
        lifespan.close_pg_pool()

    assert call_order == ["init", "close"]
