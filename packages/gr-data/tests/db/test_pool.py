"""Tests for ``gr_data.db.postgres.pool.PgConnectionPool``.

PgConnectionPool is a thin wrapper over
``psycopg_pool.AsyncConnectionPool``:

- ``init()`` is idempotent: re-calling after success is a
  no-op (the underlying pool is not re-created).
- ``connection()`` is an async context manager that yields
  a connection from the pool; it auto-returns on exit.
- ``connection()`` raises ``RuntimeError`` if ``init()``
  has not been called — a defensive guard against
  use-before-init bugs at request time.
- The connection DSN is built from 显式传入的 PostgreSQL 配置
  and forces ``application_name=getrich-web``.
- The pool kwargs set ``row_factory=dict_row`` and
  force the session timezone to ``Asia/Shanghai`` plus a
  ``search_path=app,market,meta,public`` —— 时区是 AGENTS.md §3.1 的
  项目铁律；search_path 覆盖业务主库与行情／参考数据，回测产物在
  ``backtest`` schema，由 SQL 显式加前缀，不靠 search_path。

These tests mock ``psycopg_pool.AsyncConnectionPool``
itself, so no live Postgres is required.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from gr_data.config import PostgresConfig
from gr_data.db.postgres.pool import PgConnectionPool
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row


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
    """Mimics PostgresConfig shape."""

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


def _config_context(pg_settings: _FakePgSettings | None = None):
    """显式提供配置，不修改模块全局状态。"""
    if pg_settings is None:
        pg_settings = _FakePgSettings()
    return nullcontext(pg_settings)


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
        _config_context(fake_settings) as config,
        patch(
            "gr_data.db.postgres.pool.AsyncConnectionPool",
            return_value=fake_pool,
        ) as acp_cls,
    ):
        await pool.init(config)

    acp_cls.assert_called_once()
    args, kwargs = acp_cls.call_args
    # The pool is built with `conninfo=...` (positional or keyword)
    # and `min_size`, `max_size`, `kwargs={...}`, `open=False`.
    # We pull the DSN from whichever slot the wrapper used.
    conninfo = kwargs.get("conninfo") or args[0] if args else kwargs.get("conninfo")
    assert conninfo is not None
    assert conninfo_to_dict(conninfo) == {
        "host": "pg.internal",
        "port": "6432",
        "user": "bob",
        "password": "hunter2",
        "dbname": "getrich_test",
        "application_name": "getrich-web",
    }
    assert kwargs["min_size"] == 1
    assert kwargs["max_size"] == 5
    assert kwargs["open"] is False

    inner = kwargs["kwargs"]
    assert inner["row_factory"] is dict_row
    # 时区是铁律；search_path 必须覆盖 app（业务）与 market/meta（行情、参考）。
    opts = inner["options"]
    assert "timezone=Asia/Shanghai" in opts
    assert "search_path=app,market,meta,public" in opts
    # frontend schema 已被 app + backtest 取代，不该再出现。
    assert "frontend" not in opts
    # backtest 不进 search_path：回测 SQL 一律显式写 backtest. 前缀。
    assert "backtest" not in opts

    fake_pool.open.assert_awaited_once_with(wait=True)


async def test_init_stores_underlying_pool() -> None:
    """After `init()`, the wrapper's `_pool` is the real
    pool instance returned by `AsyncConnectionPool(...)`."""
    pool = PgConnectionPool()
    fake_pool = _make_fake_async_pool()

    with (
        _config_context() as config,
        patch(
            "gr_data.db.postgres.pool.AsyncConnectionPool",
            return_value=fake_pool,
        ),
    ):
        await pool.init(config)

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
        _config_context() as config,
        patch(
            "gr_data.db.postgres.pool.AsyncConnectionPool",
        ) as acp_cls,
    ):
        await pool.init(config)

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
        _config_context() as config,
        patch(
            "gr_data.db.postgres.pool.AsyncConnectionPool",
            return_value=fake_pool,
        ),
    ):
        await pool.init(config)

    assert pool.is_ready is True
    async with pool.connection() as conn:
        assert conn is fake_conn
    await pool.close()
    assert pool.is_ready is False


async def test_init_failure_closes_pool_and_allows_retry() -> None:
    pool = PgConnectionPool()
    failed = _make_fake_async_pool()
    failed.open.side_effect = RuntimeError("unavailable")
    healthy = _make_fake_async_pool()
    with patch(
        "gr_data.db.postgres.pool.AsyncConnectionPool", side_effect=[failed, healthy]
    ) as factory:
        with pytest.raises(RuntimeError, match="unavailable"):
            await pool.init(cast(PostgresConfig, _FakePgSettings()))
        assert pool.is_ready is False
        failed.close.assert_awaited_once()
        await pool.init(cast(PostgresConfig, _FakePgSettings()))
    assert factory.call_count == 2
    assert pool._pool is healthy


async def test_init_preserves_special_password_characters() -> None:
    pool = PgConnectionPool()
    fake = _make_fake_async_pool()
    cfg = cast(PostgresConfig, _FakePgSettings(password="synthetic %'\\ value"))
    with patch("gr_data.db.postgres.pool.AsyncConnectionPool", return_value=fake) as factory:
        await pool.init(cfg)
    parsed = conninfo_to_dict(factory.call_args.kwargs["conninfo"])
    assert parsed["password"] == cfg.password


async def test_concurrent_init_waits_for_first_open() -> None:
    import asyncio

    pool = PgConnectionPool()
    fake = _make_fake_async_pool()
    started = asyncio.Event()
    finish = asyncio.Event()

    async def open_pool(*, wait: bool) -> None:
        started.set()
        await finish.wait()

    fake.open.side_effect = open_pool
    with patch("gr_data.db.postgres.pool.AsyncConnectionPool", return_value=fake) as factory:
        first = asyncio.create_task(pool.init(cast(PostgresConfig, _FakePgSettings())))
        await started.wait()
        second = asyncio.create_task(pool.init(cast(PostgresConfig, _FakePgSettings())))
        await asyncio.sleep(0)
        assert not second.done()
        assert not pool.is_ready
        finish.set()
        await asyncio.gather(first, second)
    factory.assert_called_once()


async def test_cancelled_init_closes_pool() -> None:
    import asyncio

    pool = PgConnectionPool()
    fake = _make_fake_async_pool()
    started = asyncio.Event()

    async def open_pool(*, wait: bool) -> None:
        started.set()
        await asyncio.Future()

    fake.open.side_effect = open_pool
    with patch("gr_data.db.postgres.pool.AsyncConnectionPool", return_value=fake):
        task = asyncio.create_task(pool.init(cast(PostgresConfig, _FakePgSettings())))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    fake.close.assert_awaited_once()
    assert not pool.is_ready
