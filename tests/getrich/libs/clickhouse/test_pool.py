"""Tests for ``getrich.libs.clickhouse.pool``.

The ClickHouse pool is composed of two pieces:

- ``PooledConnection`` — a thin wrapper that tracks
  lifecycle state (in_use / created_at / last_used /
  use_count / expired / idle) and delegates close to
  the underlying ``ClickHouseClient``.
- ``ClickHouseConnectionPool`` — manages a list of
  ``PooledConnection`` instances, dispatches
  ``get_connection()`` / ``release_connection()`` calls,
  and exposes stats / shrink / cleanup / health_check /
  close_all / context manager hooks.

The pool itself is synchronous (it returns
``ClickHouseClient`` instances, not awaitables), so all
tests are sync ``def``-style. ``pytestmark = anyio`` is
set so the suite runs through the project's anyio
plugin (a no-op for sync tests, but consistent with the
rest of the codebase).
"""

from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from getrich.libs.clickhouse.pool import (
    ClickHouseConnectionPool,
    PooledConnection,
)


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _Result:
    """A `result.empty` flag holder — ClickHouse returns
    a DataFrame-like result that exposes `.empty`."""

    def __init__(self, empty: bool) -> None:
        self.empty = empty


class _FakeClient:
    """Tiny stand-in for :class:`ClickHouseClient`.

    `is_connected()` returns a configurable bool so we can
    simulate a connection that has gone stale. `query()`
    returns a non-empty `_Result` by default — the pool's
    health-check treats `result.empty` as failure, so
    healthy fakes must return a non-empty result.
    """

    def __init__(
        self,
        *,
        connected: bool = True,
        ping_raises: bool = False,
        query_empty: bool = False,
    ) -> None:
        self.connected = connected
        self.ping_raises = ping_raises
        self.query_empty = query_empty
        self.closed = False
        self.ping_calls = 0
        self.query_calls: list[str] = []

    def is_connected(self) -> bool:
        return self.connected

    def ping(self) -> None:
        self.ping_calls += 1
        if self.ping_raises:
            raise RuntimeError("ping failed")

    def close(self) -> None:
        self.closed = True
        self.connected = False

    def query(self, sql: str) -> Any:
        self.query_calls.append(sql)
        return _Result(empty=self.query_empty)


def _make_pool(*, min_size: int = 1, max_size: int = 3) -> ClickHouseConnectionPool:
    """Build a pool with all `ClickHouseClient` instances
    replaced by ``_FakeClient``s.

    We bypass ``__init__`` (which would call
    `clickhouse_connect.get_client`) by hand-rolling
    the wrapper's internal state.
    """
    pool = ClickHouseConnectionPool.__new__(ClickHouseConnectionPool)
    pool.min_size = min_size
    pool.max_size = max_size
    pool.max_idle_time = 300.0
    pool.max_lifetime = 3600.0
    pool.connect_timeout = 10.0
    pool.health_check_interval = 60.0
    pool._config = {"host": "h", "port": 9000, "database": "d"}
    pool._pool = []
    pool._lock = threading.RLock()
    pool._stats = {
        "total_connections": 0,
        "active_connections": 0,
        "get_requests": 0,
        "get_timeouts": 0,
        "connections_created": 0,
        "connections_closed": 0,
        "health_checks": 0,
        "failed_health_checks": 0,
    }
    pool.logger = MagicMock()
    return pool


def _append(
    pool: ClickHouseConnectionPool,
    client: _FakeClient,
    *,
    in_use: bool = False,
) -> PooledConnection:
    """Add a hand-rolled ``PooledConnection`` to the pool."""
    conn = PooledConnection.__new__(PooledConnection)
    conn.client = client
    conn.pool = pool
    conn.in_use = in_use
    conn.created_at = time.time()
    conn.last_used = time.time()
    conn.use_count = 0
    pool._pool.append(conn)
    pool._stats["total_connections"] += 1
    return conn


def _make_pooled_connection(
    pool: ClickHouseConnectionPool,
    client: _FakeClient,
) -> PooledConnection:
    """Build a fresh PooledConnection (used when patching
    `_create_connection` to short-circuit a real driver call)."""
    pc = PooledConnection.__new__(PooledConnection)
    pc.client = client
    pc.pool = pool
    pc.in_use = False
    pc.created_at = time.time()
    pc.last_used = time.time()
    pc.use_count = 0
    return pc


# ---------------------------------------------------------------------------
# PooledConnection: state
# ---------------------------------------------------------------------------


def test_pooled_connection_mark_in_use_sets_state() -> None:
    """`mark_in_use()` flips the flag, refreshes
    `last_used`, and increments `use_count`."""
    conn = PooledConnection.__new__(PooledConnection)
    conn.client = MagicMock()
    conn.pool = MagicMock()
    conn.in_use = False
    conn.created_at = time.time()
    conn.last_used = 0.0
    conn.use_count = 0

    conn.mark_in_use()

    assert conn.in_use is True
    assert conn.last_used > 0
    assert conn.use_count == 1


def test_pooled_connection_mark_available_clears_state() -> None:
    conn = PooledConnection.__new__(PooledConnection)
    conn.client = MagicMock()
    conn.pool = MagicMock()
    conn.in_use = True
    conn.created_at = time.time()
    conn.last_used = 0.0
    conn.use_count = 5

    conn.mark_available()

    assert conn.in_use is False
    assert conn.last_used > 0
    # use_count is preserved — it's a lifetime counter.
    assert conn.use_count == 5


# ---------------------------------------------------------------------------
# PooledConnection: expiry / idle
# ---------------------------------------------------------------------------


def test_pooled_connection_is_expired_false_when_fresh() -> None:
    conn = PooledConnection.__new__(PooledConnection)
    conn.client = MagicMock()
    conn.pool = MagicMock()
    conn.created_at = time.time()
    conn.last_used = time.time()

    assert conn.is_expired(max_age=3600) is False


def test_pooled_connection_is_expired_true_when_old() -> None:
    conn = PooledConnection.__new__(PooledConnection)
    conn.client = MagicMock()
    conn.pool = MagicMock()
    conn.created_at = time.time() - 7200  # 2h ago
    conn.last_used = time.time()

    assert conn.is_expired(max_age=3600) is True


def test_pooled_connection_is_idle_timeout_false_when_recent() -> None:
    conn = PooledConnection.__new__(PooledConnection)
    conn.client = MagicMock()
    conn.pool = MagicMock()
    conn.created_at = time.time() - 1000
    conn.last_used = time.time()  # used just now

    assert conn.is_idle_timeout(idle_timeout=300) is False


def test_pooled_connection_is_idle_timeout_true_when_idle() -> None:
    conn = PooledConnection.__new__(PooledConnection)
    conn.client = MagicMock()
    conn.pool = MagicMock()
    conn.created_at = time.time() - 1000
    conn.last_used = time.time() - 600  # idle 10min

    assert conn.is_idle_timeout(idle_timeout=300) is True


def test_pooled_connection_close_delegates() -> None:
    """`close()` calls the underlying client's `close()`."""
    fake = _FakeClient()
    conn = PooledConnection.__new__(PooledConnection)
    conn.client = fake
    conn.pool = MagicMock()
    conn.in_use = False
    conn.created_at = time.time()
    conn.last_used = time.time()
    conn.use_count = 0

    conn.close()

    assert fake.closed is True


def test_pooled_connection_close_swallows_missing_client() -> None:
    """If `client` is None (e.g. after a prior failed
    init), `close()` does NOT raise — the `if self.client:`
    guard handles it."""
    conn = PooledConnection.__new__(PooledConnection)
    conn.client = None
    conn.pool = MagicMock()
    conn.in_use = False
    conn.created_at = time.time()
    conn.last_used = time.time()
    conn.use_count = 0

    conn.close()  # should NOT raise


# ---------------------------------------------------------------------------
# ClickHouseConnectionPool: repr / config display
# ---------------------------------------------------------------------------


def test_get_config_display_hides_password() -> None:
    """`_get_config_display()` is the logging helper that
    hides the password from INFO output."""
    pool = _make_pool()
    pool._config = {"host": "h", "password": "hunter2", "database": "d"}

    rendered = pool._get_config_display()

    assert "hunter2" not in rendered
    assert "***" in rendered
    assert "'host': 'h'" in rendered


# ---------------------------------------------------------------------------
# ClickHouseConnectionPool: get / release
# ---------------------------------------------------------------------------


def test_get_connection_reuses_idle_client() -> None:
    """If an idle, healthy client is available, it's
    returned without creating a new one."""
    pool = _make_pool(min_size=1, max_size=2)
    fake = _FakeClient()
    conn = _append(pool, fake)

    out = pool.get_connection(timeout=0.5)

    # The pool returns the underlying client (`fake`),
    # not the PooledConnection wrapper.
    assert out is fake
    assert conn.in_use is True
    assert pool._stats["active_connections"] == 1


def test_get_connection_creates_when_pool_below_max() -> None:
    """If the pool is empty (or all conns are in use) AND
    `len(_pool) < max_size`, `_create_connection()` is
    called and the new client is returned."""
    pool = _make_pool(min_size=0, max_size=2)
    fresh = _FakeClient()
    pc = _make_pooled_connection(pool, fresh)

    with patch.object(pool, "_create_connection", return_value=pc):
        out = pool.get_connection(timeout=0.5)

    assert out is fresh
    assert pool._stats["active_connections"] == 1
    # The new PooledConnection is appended to the pool
    # and marked in_use. (The `connections_created`
    # counter is bumped inside `_create_connection` —
    # which we patched out, so we don't assert on it.)
    assert len(pool._pool) == 1
    assert pool._pool[0].client is fresh
    assert pool._pool[0].in_use is True


def test_get_connection_removes_unhealthy_existing() -> None:
    """When an idle client is found but is no longer
    connected, the pool drops it and tries again. With
    a single conn and a fresh-create fallback, the new
    fake becomes the live one."""
    pool = _make_pool(min_size=0, max_size=2)
    bad = _FakeClient(connected=False)
    _append(pool, bad)

    fresh = _FakeClient()
    pc = _make_pooled_connection(pool, fresh)
    with patch.object(pool, "_create_connection", return_value=pc):
        out = pool.get_connection(timeout=0.5)

    # The bad conn was removed; only the new one remains.
    assert out is fresh
    assert len(pool._pool) == 1
    assert pool._pool[0].client is fresh
    assert pool._stats["connections_closed"] == 1


def test_get_connection_timeout_raises_when_saturated() -> None:
    """If `len(_pool) == max_size` and all conns are in
    use, the pool raises `TimeoutError` after the
    timeout elapses. (We use a tiny timeout + patched
    sleep to keep the test fast.)"""
    pool = _make_pool(min_size=0, max_size=1)
    busy = _FakeClient()
    _append(pool, busy, in_use=True)

    # Short-circuit _create_connection (returns None →
    # loop continues) and patch time.sleep so the test
    # doesn't actually wait.
    with (
        patch.object(pool, "_create_connection", return_value=None),
        patch("getrich.libs.clickhouse.pool.time.sleep"),
        pytest.raises(TimeoutError, match="Could not get connection"),
    ):
        pool.get_connection(timeout=0.05)

    assert pool._stats["get_timeouts"] == 1


def test_release_connection_marks_available() -> None:
    pool = _make_pool(min_size=1, max_size=1)
    fake = _FakeClient()
    pc = _append(pool, fake, in_use=True)
    pool._stats["active_connections"] = 1

    pool.release_connection(fake)

    assert pc.in_use is False
    assert pool._stats["active_connections"] == 0


def test_release_connection_unknown_warns_and_does_nothing() -> None:
    """Releasing a client that is not in the pool is
    silently ignored (with a warning log)."""
    pool = _make_pool(min_size=1, max_size=1)
    stranger = _FakeClient()

    pool.release_connection(stranger)

    assert pool._stats["active_connections"] == 0
    pool.logger.warning.assert_called()


def test_release_connection_already_available_is_noop() -> None:
    """If the matching PooledConnection is found but
    `in_use` is already False, the pool skips the
    `mark_available` step and the active count isn't
    decremented (avoids going negative)."""
    pool = _make_pool(min_size=1, max_size=1)
    fake = _FakeClient()
    pc = _append(pool, fake, in_use=False)
    pool._stats["active_connections"] = 0

    pool.release_connection(fake)

    assert pc.in_use is False
    assert pool._stats["active_connections"] == 0


# ---------------------------------------------------------------------------
# Context-manager `connection()` (sync!)
# ---------------------------------------------------------------------------


def test_connection_context_manager_gets_and_releases() -> None:
    """`pool.connection()` is a SYNC context manager
    (the pool itself is sync, not async). It yields the
    client and releases it on exit."""
    pool = _make_pool(min_size=1, max_size=1)
    fake = _FakeClient()
    _append(pool, fake)

    with pool.connection() as c:
        assert c is fake
        assert pool._stats["active_connections"] == 1

    assert pool._stats["active_connections"] == 0


def test_connection_context_manager_releases_on_exception() -> None:
    """If the with-block raises, the connection is still
    released back to the pool — the `finally` clause
    in `connection()` handles it."""
    pool = _make_pool(min_size=1, max_size=1)
    fake = _FakeClient()
    _append(pool, fake)

    with pytest.raises(RuntimeError, match="boom"), pool.connection():
        assert pool._stats["active_connections"] == 1
        raise RuntimeError("boom")

    assert pool._stats["active_connections"] == 0


# ---------------------------------------------------------------------------
# Health-check
# ---------------------------------------------------------------------------


def test_health_check_removes_disconnected_clients() -> None:
    """`health_check()` runs `SELECT 1` per client and
    drops the ones whose result is `empty` (or which
    raise). The `is_connected` flag is NOT consulted
    here — only the query result. (`is_connected` is
    consulted by `_is_connection_healthy`, which
    `get_connection` uses; `health_check` goes one level
    deeper with an actual query.)"""
    pool = _make_pool(min_size=1, max_size=2)
    bad = _FakeClient(query_empty=True)  # `SELECT 1` returns empty
    _append(pool, bad)

    pool.health_check()

    assert pool._pool == []
    assert pool._stats["failed_health_checks"] == 1
    assert bad.closed is True
    assert any("SELECT 1" in c for c in bad.query_calls)


def test_health_check_keeps_healthy_clients() -> None:
    pool = _make_pool(min_size=1, max_size=2)
    healthy = _FakeClient(connected=True)
    _append(pool, healthy)

    pool.health_check()

    assert len(pool._pool) == 1
    assert pool._pool[0].client is healthy
    assert pool._stats["health_checks"] == 1
    assert pool._stats["failed_health_checks"] == 0


def test_health_check_skips_in_use_clients() -> None:
    """In-use clients are skipped — we don't want a
    background health check yanking a connection out
    from under an active query."""
    pool = _make_pool(min_size=1, max_size=2)
    busy = _FakeClient(connected=False)
    _append(pool, busy, in_use=True)

    pool.health_check()

    # Not removed (was in use at the time of the check).
    assert len(pool._pool) == 1
    assert pool._pool[0].client is busy
    assert pool._stats["failed_health_checks"] == 0


def test_health_check_counts_failed_query() -> None:
    """If `SELECT 1` raises, the client is removed and
    `failed_health_checks` is bumped."""
    pool = _make_pool(min_size=1, max_size=1)
    faulty = _FakeClient()

    def _raise(_sql: str):
        raise RuntimeError("connection reset")

    faulty.query = _raise  # type: ignore[method-assign]
    _append(pool, faulty)

    pool.health_check()

    assert pool._pool == []
    assert pool._stats["failed_health_checks"] == 1


# ---------------------------------------------------------------------------
# Cleanup / shrink
# ---------------------------------------------------------------------------


def test_cleanup_drops_unhealthy_idle_clients() -> None:
    pool = _make_pool(min_size=0, max_size=2)
    bad = _FakeClient(connected=False)
    good = _FakeClient(connected=True)
    _append(pool, bad)
    _append(pool, good)

    pool.cleanup()

    # `cleanup` ensures at least `min_size` conns after
    # the sweep — but with min_size=0 we don't refill.
    assert len(pool._pool) == 1
    assert pool._pool[0].client is good


def test_cleanup_refills_up_to_min_size() -> None:
    """If cleanup drops below `min_size`, it creates
    new conns to top back up."""
    pool = _make_pool(min_size=1, max_size=2)
    bad = _FakeClient(connected=False)
    _append(pool, bad)

    fresh = _FakeClient()
    pc = _make_pooled_connection(pool, fresh)
    with patch.object(pool, "_create_connection", return_value=pc):
        pool.cleanup()

    assert len(pool._pool) == 1
    assert pool._pool[0].client is fresh


def test_shrink_closes_idle_above_active_count() -> None:
    """`shrink()` removes idle conns down to
    `max(min_size, active_connections)`. The oldest idle
    conn is closed first (sorted by `last_used`)."""
    pool = _make_pool(min_size=1, max_size=4)
    fresh = _FakeClient(connected=True)
    stale = _FakeClient(connected=True)
    _append(pool, fresh)
    _append(pool, stale)
    pool._pool[0].last_used = time.time()  # newer
    pool._pool[1].last_used = time.time() - 1000  # older

    pool.shrink()

    # With 0 active and min_size=1, we keep the newest
    # idle conn and drop the older one.
    assert len(pool._pool) == 1
    assert pool._pool[0].client is fresh
    assert stale.closed is True


def test_shrink_keeps_active_count_safe() -> None:
    """Even if min_size is 0, `shrink()` keeps at least
    `active_connections` conns alive (so it never
    destroys conns currently in use)."""
    pool = _make_pool(min_size=0, max_size=4)
    a = _FakeClient(connected=True)
    b = _FakeClient(connected=True)
    c = _FakeClient(connected=True)
    _append(pool, a, in_use=True)
    _append(pool, b, in_use=True)
    _append(pool, c, in_use=False)

    pool._stats["active_connections"] = 2
    pool.shrink()

    # target_size = max(0, 2) = 2, current = 3,
    # to_close = 1 → only the oldest idle (c) is removed.
    assert len(pool._pool) == 2
    assert c.closed is True


# ---------------------------------------------------------------------------
# close_all / context manager
# ---------------------------------------------------------------------------


def test_close_all_drains_pool_and_resets_counters() -> None:
    pool = _make_pool(min_size=1, max_size=2)
    a = _FakeClient()
    b = _FakeClient()
    _append(pool, a)
    _append(pool, b)

    pool.close_all()

    assert pool._pool == []
    assert pool._stats["total_connections"] == 0
    assert pool._stats["active_connections"] == 0
    assert a.closed is True
    assert b.closed is True


def test_context_manager_closes_all_on_exit() -> None:
    pool = _make_pool(min_size=1, max_size=2)
    fake = _FakeClient()
    _append(pool, fake)

    with pool:
        assert len(pool._pool) == 1
        assert pool._pool[0].client is fake

    assert pool._pool == []
    assert fake.closed is True


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def test_get_stats_includes_pool_size_and_idle() -> None:
    """`get_stats()` adds `pool_size` and
    `idle_connections` on top of the internal counters."""
    pool = _make_pool(min_size=1, max_size=3)
    a = _FakeClient(connected=True)
    b = _FakeClient(connected=True)
    _append(pool, a, in_use=True)
    _append(pool, b, in_use=False)

    stats = pool.get_stats()

    assert stats["pool_size"] == 2
    assert stats["idle_connections"] == 1
    assert stats["total_connections"] == 2
    assert stats["active_connections"] == 0


def test_get_stats_returns_copy() -> None:
    """The returned dict is a copy: mutating it does
    not affect the wrapper's internal counters."""
    pool = _make_pool()
    stats = pool.get_stats()

    stats["total_connections"] = 9999

    assert pool._stats["total_connections"] == 0


# ---------------------------------------------------------------------------
# Repr
# ---------------------------------------------------------------------------


def test_repr_hides_password() -> None:
    pool = _make_pool()
    pool._config = {"host": "click.internal", "password": "secret", "database": "goldmine"}

    rendered = repr(pool)

    assert "secret" not in rendered
    assert "***" in rendered
    assert "click.internal" in rendered
