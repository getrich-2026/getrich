"""Tests for ``getrich.libs.postgres.pool.PgConnectionPool``.

PgConnectionPool is a thin wrapper over
``psycopg_pool.AsyncConnectionPool``:

- ``init()`` is idempotent: re-calling after success is a
  no-op (the underlying pool is not re-created).
- ``connection()`` is an async context manager that yields
  a connection from the pool; it auto-returns on exit.
- ``connection()`` raises ``RuntimeError`` if ``init()``
  has not been called — a defensive guard against
  use-before-init bugs at request time.
- The connection DSN is built from ``settings.postgres``
  and forces ``application_name=getrich-web``.
- The pool kwargs set ``row_factory=dict_row`` and
  force the session timezone to ``Asia/Shanghai`` plus a
  ``search_path=frontend`` — both are project invariants
  declared in CLAUDE.md §3.1.

These tests mock ``psycopg_pool.AsyncConnectionPool``
itself, so no live Postgres is required.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from psycopg.rows import dict_row

from getrich.libs.postgres.pool import PgConnectionPool


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


def _make_async_cm_mock(conn_obj: Any) -> AsyncMock:
    """Build an async context manager that yields ``conn_obj``."""
    cm = AsyncMock()
    cm.__aenter__.return_value = conn_obj
    cm.__aexit__.return_value = False
    return cm


def _make_fake_async_pool() -> MagicMock:
    """Build a MagicMock that quacks like
    ``psycopg_pool.AsyncConnectionPool``.

    The real pool exposes ``.open()`` (coroutine),
    ``.close()`` (coroutine), and ``.connection()``
    (async context manager). We mock all three.
    """
    fake_pool = MagicMock()
    fake_pool.open = AsyncMock()
    fake_pool.close = AsyncMock()
    # `.connection()` returns an async CM:
    fake_pool.connection = MagicMock(
        return_value=_make_async_cm_mock(MagicMock(name="fake_conn")),
    )
    return fake_pool


class _FakePgSettings:
    """Mimics ``getrich.config.settings.postgres`` shape."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        user: str = "alice",
        password: str = "secret",
        database: str = "getrich",
        min_size: int = 2,
        max_size: int = 10,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.min_size = min_size
        self.max_size = max_size


def _patch_settings(pg_settings: _FakePgSettings | None = None):
    """Patch ``getrich.config.settings`` so the lazy import
    inside ``PgConnectionPool.init()`` returns our fake."""
    if pg_settings is None:
        pg_settings = _FakePgSettings()
    fake_settings = MagicMock()
    fake_settings.postgres = pg_settings
    return patch("getrich.config.settings", fake_settings)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_constructor_does_not_open_pool() -> None:
    """``PgConnectionPool.__init__`` must NOT call the
    underlying pool — connection is deferred to ``init()``,
    which is called explicitly at app startup."""
    pool = PgConnectionPool()

    assert pool._pool is None
    assert pool.is_ready is False


# ---------------------------------------------------------------------------
# is_ready
# ---------------------------------------------------------------------------


def test_is_ready_false_before_init() -> None:
    pool = PgConnectionPool()
    assert pool.is_ready is False


def test_is_ready_true_after_init() -> None:
    pool = PgConnectionPool()
    pool._pool = MagicMock(name="underlying")

    assert pool.is_ready is True


# ---------------------------------------------------------------------------
# init() — happy path
# ---------------------------------------------------------------------------


async def test_init_creates_pool_with_expected_dsn_and_kwargs() -> None:
    """`init()` builds the DSN from `settings.postgres` and
    forwards min/max + `row_factory=dict_row` + the
    timezone/search_path `options` to `AsyncConnectionPool`."""
    pool = PgConnectionPool()
    fake_pool = _make_fake_async_pool()
    fake_settings = _FakePgSettings(
        host="pg.internal",
        port=6432,
        user="bob",
        password="hunter2",
        database="getrich_test",
        min_size=1,
        max_size=5,
    )

    with (
        _patch_settings(fake_settings),
        patch(
            "getrich.libs.postgres.pool.AsyncConnectionPool",
            return_value=fake_pool,
        ) as acp_cls,
    ):
        await pool.init()

    acp_cls.assert_called_once()
    args, kwargs = acp_cls.call_args
    # The pool is built with `conninfo=...` (positional or keyword)
    # and `min_size`, `max_size`, `kwargs={...}`, `open=False`.
    # We pull the DSN from whichever slot the wrapper used.
    conninfo = kwargs.get("conninfo") or args[0] if args else kwargs.get("conninfo")
    assert conninfo is not None
    assert "postgresql://bob:hunter2@pg.internal:6432/getrich_test" in conninfo
    assert "application_name=getrich-web" in conninfo
    assert kwargs["min_size"] == 1
    assert kwargs["max_size"] == 5
    assert kwargs["open"] is False

    inner = kwargs["kwargs"]
    assert inner["row_factory"] is dict_row
    # The project mandates the +08:00 timezone and the
    # `frontend` schema search_path. The full options
    # string is encoded into a single `-c ...` flag pair.
    opts = inner["options"]
    assert "timezone=Asia/Shanghai" in opts
    assert "search_path=frontend" in opts

    fake_pool.open.assert_awaited_once_with(wait=True)


async def test_init_stores_underlying_pool() -> None:
    """After `init()`, the wrapper's `_pool` is the real
    pool instance returned by `AsyncConnectionPool(...)`."""
    pool = PgConnectionPool()
    fake_pool = _make_fake_async_pool()

    with (
        _patch_settings(),
        patch(
            "getrich.libs.postgres.pool.AsyncConnectionPool",
            return_value=fake_pool,
        ),
    ):
        await pool.init()

    assert pool._pool is fake_pool


# ---------------------------------------------------------------------------
# init() — idempotency
# ---------------------------------------------------------------------------


async def test_init_is_idempotent() -> None:
    """A second `init()` call after success is a no-op.
    The wrapper returns early (`if self._pool is not None`)
    before re-creating the underlying pool."""
    pool = PgConnectionPool()
    fake_pool = _make_fake_async_pool()
    pool._pool = fake_pool  # pretend init() already ran

    with (
        _patch_settings(),
        patch(
            "getrich.libs.postgres.pool.AsyncConnectionPool",
        ) as acp_cls,
    ):
        await pool.init()

    acp_cls.assert_not_called()
    # And we did NOT call .open() on the existing pool.
    fake_pool.open.assert_not_awaited()


# ---------------------------------------------------------------------------
# connection() — happy path
# ---------------------------------------------------------------------------


async def test_connection_yields_conn_from_underlying_pool() -> None:
    """`connection()` is a passthrough async CM that yields
    whatever the underlying `AsyncConnectionPool.connection()`
    yields."""
    pool = PgConnectionPool()
    fake_pool = _make_fake_async_pool()
    fake_conn = MagicMock(name="postgres_conn")
    fake_pool.connection = MagicMock(
        return_value=_make_async_cm_mock(fake_conn),
    )
    pool._pool = fake_pool

    async with pool.connection() as conn:
        assert conn is fake_conn


# ---------------------------------------------------------------------------
# connection() — guard
# ---------------------------------------------------------------------------


async def test_connection_raises_runtime_error_when_not_initialized() -> None:
    """`connection()` is the hot path; calling it before
    `init()` raises `RuntimeError` (rather than a confusing
    AttributeError on None)."""
    pool = PgConnectionPool()

    with pytest.raises(RuntimeError, match="init"):
        async with pool.connection():
            pytest.fail("connection() should not yield when uninitialized")  # pragma: no cover


# ---------------------------------------------------------------------------
# close()
# ---------------------------------------------------------------------------


async def test_close_closes_underlying_pool() -> None:
    pool = PgConnectionPool()
    fake_pool = _make_fake_async_pool()
    pool._pool = fake_pool

    await pool.close()

    fake_pool.close.assert_awaited_once()
    assert pool._pool is None


async def test_close_is_safe_when_not_initialized() -> None:
    """Calling `close()` before `init()` is a documented
    no-op (the wrapper's `if self._pool is not None`
    guard)."""
    pool = PgConnectionPool()

    await pool.close()  # should NOT raise

    assert pool._pool is None


# ---------------------------------------------------------------------------
# Lifecycle integration
# ---------------------------------------------------------------------------


async def test_full_lifecycle_init_connection_close() -> None:
    """`init()` → `connection()` → `close()` runs end-to-end
    without raising. We mock the underlying pool, so the
    connection context manager returns a sentinel conn."""
    pool = PgConnectionPool()
    fake_pool = _make_fake_async_pool()
    fake_conn = MagicMock(name="conn")
    fake_pool.connection = MagicMock(
        return_value=_make_async_cm_mock(fake_conn),
    )

    with (
        _patch_settings(),
        patch(
            "getrich.libs.postgres.pool.AsyncConnectionPool",
            return_value=fake_pool,
        ),
    ):
        await pool.init()

    assert pool.is_ready is True
    async with pool.connection() as conn:
        assert conn is fake_conn
    await pool.close()
    assert pool.is_ready is False
