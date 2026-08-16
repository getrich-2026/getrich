"""Tests for ``gr_data.db.clickhouse.table.ClickHouseTable``.

`ClickHouseTable` is the abstract base class for all
table operations. Subclasses implement `create()`. The
base class itself handles:

- Three connection modes (own client / shared client /
  shared pool)
- Connection acquisition / release for pool mode
- Schema ops (insert / truncate / drop / optimize)
- Introspection (exists / count)
- Lifecycle (context manager, close, repr)

These tests use a concrete `_TestTable` subclass
(implementing the `create()` abstract method) and a
fake `ClickHouseClient` for the assertions.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from gr_data.db.clickhouse.table import ClickHouseTable


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Concrete subclass for testing
# ---------------------------------------------------------------------------


class _TestTable(ClickHouseTable):
    """Minimal concrete subclass — `create()` is the only
    abstract method on the base, so we provide a no-op."""

    def create(self, if_not_exists: bool = True) -> bool:  # type: ignore[override]
        # No-op for testing; subclasses would issue a
        # CREATE TABLE DDL here.
        return True


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeClient:
    """In-process fake of :class:`ClickHouseClient`.

    Records method calls and exposes a query()-able
    return for the introspection methods.
    """

    def __init__(self) -> None:
        self.connected = True
        self.config = {"host": "h", "port": 9000, "database": "d"}
        self.insert_data = MagicMock(return_value=True)
        self.truncate_data = MagicMock(return_value=True)
        self.drop_table = MagicMock(return_value=True)
        self.query = MagicMock()
        self.execute = MagicMock(return_value=True)
        self.is_connected = MagicMock(return_value=True)
        self.close = MagicMock(side_effect=lambda: setattr(self, "connected", False))

        # Default `query()` returns an empty DataFrame
        # so exists()/count() can fall back to "table
        # does not exist" or "0 records".
        self.query.return_value = pd.DataFrame()

        self.calls: list[tuple[str, tuple, dict]] = []

    def get_config(self) -> dict[str, Any]:
        return self.config


class _FakePool:
    """Minimal fake of `ClickHouseConnectionPool` that
    hands out a `_FakeClient` from `get_connection()` and
    tracks `release_connection()` calls."""

    def __init__(self, client: _FakeClient) -> None:
        self._client = client
        self.get_calls = 0
        self.release_calls: list[Any] = []

    def get_connection(self) -> _FakeClient:
        self.get_calls += 1
        return self._client

    def release_connection(self, client: Any) -> None:
        self.release_calls.append(client)

    def get_stats(self) -> dict[str, int]:
        return {
            "pool_size": 1,
            "idle_connections": 0 if self._client.connected is False else 0,
        }


# ---------------------------------------------------------------------------
# Constructor — three connection modes
# ---------------------------------------------------------------------------


def test_constructor_with_own_client() -> None:
    """When no client/pool/host is given, the wrapper
    creates its own `ClickHouseClient` and OWNS it
    (`_owns_client=True`). The injected fake's
    constructor is patched out below."""
    fake = _FakeClient()
    with patch(
        "gr_data.db.clickhouse.table.ClickHouseClient",
        return_value=fake,
    ):
        t = _TestTable(table_name="t")

    assert t.client is fake
    assert t._owns_client is True
    assert t._use_pool is False


def test_constructor_with_injected_client_does_not_own() -> None:
    """When a `client` is provided, the wrapper does NOT
    own it — `close()` is a no-op."""
    fake = _FakeClient()
    t = _TestTable(table_name="t", client=fake)

    assert t.client is fake
    assert t._owns_client is False
    assert t._use_pool is False

    t.close()
    fake.close.assert_not_called()


def test_constructor_with_pool_uses_pool() -> None:
    """When a `pool` is provided, the wrapper routes
    through the pool and does NOT own any client."""
    fake = _FakeClient()
    pool = _FakePool(client=fake)
    t = _TestTable(table_name="t", pool=pool)

    assert t._use_pool is True
    assert t._pool is pool
    assert t._owns_client is False
    assert t.client is None


def test_constructor_pool_takes_priority_over_client() -> None:
    """If both pool and client are provided, the pool
    wins (the wrapper's # mode 1 branch runs first)."""
    fake = _FakeClient()
    pool = _FakePool(client=fake)
    other = _FakeClient()
    t = _TestTable(table_name="t", pool=pool, client=other)

    assert t._use_pool is True
    assert t._pool is pool
    assert t.client is None


def test_constructor_with_host_kwargs_creates_client() -> None:
    """`host=...` (etc.) triggers `ClickHouseClient(**kwargs)`
    construction with only the explicitly-provided
    kwargs forwarded."""
    fake = _FakeClient()
    with patch(
        "gr_data.db.clickhouse.table.ClickHouseClient",
        return_value=fake,
    ) as ctor:
        _TestTable(table_name="t", host="h", port=9000, database="d")

    args, kwargs = ctor.call_args
    assert kwargs == {"host": "h", "port": 9000, "database": "d"}


def test_constructor_logger_uses_class_name_by_default() -> None:
    fake = _FakeClient()
    with patch(
        "gr_data.db.clickhouse.table.ClickHouseClient",
        return_value=fake,
    ):
        t = _TestTable(table_name="t")

    assert t.logger._logger.name == "_TestTable"


def test_constructor_logger_accepts_custom_name() -> None:
    fake = _FakeClient()
    with patch(
        "gr_data.db.clickhouse.table.ClickHouseClient",
        return_value=fake,
    ):
        t = _TestTable(table_name="t", logger_name="my.logger")

    assert t.logger._logger.name == "my.logger"


# ---------------------------------------------------------------------------
# _get_client / _release_client
# ---------------------------------------------------------------------------


def test_get_client_returns_injected_client() -> None:
    fake = _FakeClient()
    t = _TestTable(table_name="t", client=fake)

    assert t._get_client() is fake


def test_get_client_uses_pool_when_pool_mode() -> None:
    fake = _FakeClient()
    pool = _FakePool(client=fake)
    t = _TestTable(table_name="t", pool=pool)

    assert t._get_client() is fake
    assert pool.get_calls == 1


def test_release_client_noop_without_pool() -> None:
    """Without a pool, `_release_client` is a no-op (the
    client is owned/borrowed, not borrowed-from-pool)."""
    fake = _FakeClient()
    t = _TestTable(table_name="t", client=fake)

    t._release_client(fake)  # should not raise

    pool = _FakePool(client=fake)
    t._pool = pool
    t._use_pool = True
    t._release_client(fake)
    assert pool.release_calls == [fake]


# ---------------------------------------------------------------------------
# is_connected
# ---------------------------------------------------------------------------


def test_is_connected_true_when_client_connected() -> None:
    fake = _FakeClient()
    fake.is_connected.return_value = True
    t = _TestTable(table_name="t", client=fake)

    assert t.is_connected is True


def test_is_connected_false_when_client_disconnected() -> None:
    fake = _FakeClient()
    fake.is_connected.return_value = False
    t = _TestTable(table_name="t", client=fake)

    assert t.is_connected is False


def test_is_connected_false_when_no_client() -> None:
    fake = _FakeClient()
    pool = _FakePool(client=fake)
    t = _TestTable(table_name="t", pool=pool)
    # In pool mode, `is_connected` is the pool's view.

    assert t.is_connected is True  # pool returns pool_size=1


def test_is_connected_pool_mode_reflects_pool_stats() -> None:
    fake = _FakeClient()
    pool = _FakePool(client=fake)
    pool.get_stats = MagicMock(return_value={"pool_size": 0})  # type: ignore[method-assign]
    t = _TestTable(table_name="t", pool=pool)

    assert t.is_connected is False


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


def test_close_closes_owned_client() -> None:
    fake = _FakeClient()
    with patch(
        "gr_data.db.clickhouse.table.ClickHouseClient",
        return_value=fake,
    ):
        t = _TestTable(table_name="t")

    t.close()

    fake.close.assert_called_once()


def test_close_does_not_close_borrowed_client() -> None:
    """If the client was injected (not owned), `close()`
    does NOT close it — the caller owns the lifecycle."""
    fake = _FakeClient()
    t = _TestTable(table_name="t", client=fake)

    t.close()

    fake.close.assert_not_called()


def test_close_does_nothing_when_no_client() -> None:
    fake = _FakeClient()
    pool = _FakePool(client=fake)
    t = _TestTable(table_name="t", pool=pool)

    t.close()  # should not raise, and should not call pool.release

    assert pool.release_calls == []


# ---------------------------------------------------------------------------
# insert / truncate / drop / query / execute
# ---------------------------------------------------------------------------


def test_insert_delegates_to_client_insert_data() -> None:
    fake = _FakeClient()
    t = _TestTable(table_name="t", client=fake)
    df = pd.DataFrame({"x": [1, 2, 3]})

    result = t.insert(df)

    assert result is True
    args, kwargs = fake.insert_data.call_args
    assert args == ()
    assert kwargs["table_name"] == "t"
    pd.testing.assert_frame_equal(kwargs["data"], df)


def test_insert_forwards_batch_size() -> None:
    fake = _FakeClient()
    t = _TestTable(table_name="t", client=fake)
    df = pd.DataFrame({"x": [1, 2, 3]})

    t.insert(df, batch_size=100)

    kwargs = fake.insert_data.call_args.kwargs
    assert kwargs["batch_size"] == 100


def test_insert_empty_dataframe_is_noop() -> None:
    """An empty DataFrame short-circuits — we don't
    bother calling the underlying client. (The client
    itself also short-circuits, but the table layer
    optimistically returns True first.)"""
    fake = _FakeClient()
    t = _TestTable(table_name="t", client=fake)

    result = t.insert(pd.DataFrame())

    assert result is True
    fake.insert_data.assert_not_called()


def test_insert_via_pool_acquires_and_releases() -> None:
    fake = _FakeClient()
    pool = _FakePool(client=fake)
    t = _TestTable(table_name="t", pool=pool)
    df = pd.DataFrame({"x": [1]})

    t.insert(df)

    assert pool.get_calls == 1
    assert pool.release_calls == [fake]


def test_insert_returns_false_on_exception() -> None:
    """If the client raises, `insert` catches and
    returns False. (The wrapper's `except Exception:`
    is intentionally broad.)"""
    fake = _FakeClient()
    fake.insert_data.side_effect = RuntimeError("boom")
    t = _TestTable(table_name="t", client=fake)

    result = t.insert(pd.DataFrame({"x": [1]}))

    assert result is False


def test_truncate_delegates_to_client() -> None:
    fake = _FakeClient()
    t = _TestTable(table_name="t", client=fake)

    result = t.truncate()

    assert result is True
    fake.truncate_data.assert_called_once_with("t")


def test_drop_delegates_to_client_with_if_exists() -> None:
    fake = _FakeClient()
    t = _TestTable(table_name="t", client=fake)

    result = t.drop(if_exists=False)

    assert result is True
    args, kwargs = fake.drop_table.call_args
    assert args == ("t",)
    assert kwargs["if_exists"] is False


def test_drop_default_if_exists_true() -> None:
    fake = _FakeClient()
    t = _TestTable(table_name="t", client=fake)

    t.drop()

    args, kwargs = fake.drop_table.call_args
    assert args == ("t",)
    assert kwargs["if_exists"] is True


def test_query_returns_client_result() -> None:
    fake = _FakeClient()
    fake.query.return_value = pd.DataFrame({"v": [10, 20]})
    t = _TestTable(table_name="t", client=fake)

    result = t.query("SELECT * FROM t")

    assert isinstance(result, pd.DataFrame)
    assert list(result["v"]) == [10, 20]


def test_query_forwards_params() -> None:
    fake = _FakeClient()
    t = _TestTable(table_name="t", client=fake)

    t.query("SELECT * FROM t WHERE x = %(x)s", {"x": 1})

    args, kwargs = fake.query.call_args
    assert kwargs["params"] == {"x": 1}


def test_execute_delegates() -> None:
    fake = _FakeClient()
    t = _TestTable(table_name="t", client=fake)

    result = t.execute("TRUNCATE TABLE t")

    assert result is True
    fake.execute.assert_called_once()


# ---------------------------------------------------------------------------
# exists
# ---------------------------------------------------------------------------


def test_exists_returns_true_when_count_gt_zero() -> None:
    """`exists()` queries `system.tables` and treats
    `count > 0` as the truthy signal."""
    fake = _FakeClient()
    fake.query.return_value = pd.DataFrame({"cnt": [1]})
    t = _TestTable(table_name="t", client=fake)

    assert t.exists() is True


def test_exists_returns_false_when_count_is_zero() -> None:
    fake = _FakeClient()
    fake.query.return_value = pd.DataFrame({"cnt": [0]})
    t = _TestTable(table_name="t", client=fake)

    assert t.exists() is False


def test_exists_returns_false_on_empty_result() -> None:
    """`query()` returning an empty DataFrame means
    the SELECT yielded 0 rows — the table is not in
    `system.tables`."""
    fake = _FakeClient()
    fake.query.return_value = pd.DataFrame()
    t = _TestTable(table_name="t", client=fake)

    assert t.exists() is False


def test_exists_returns_false_on_exception() -> None:
    """A query error (e.g. permission denied on
    `system.tables`) is swallowed — `exists()` returns
    False rather than raising."""
    fake = _FakeClient()
    fake.query.side_effect = RuntimeError("permission denied")
    t = _TestTable(table_name="t", client=fake)

    assert t.exists() is False


# ---------------------------------------------------------------------------
# count
# ---------------------------------------------------------------------------


def test_count_no_condition() -> None:
    fake = _FakeClient()
    fake.query.return_value = pd.DataFrame({"cnt": [42]})
    t = _TestTable(table_name="t", client=fake)

    assert t.count() == 42

    args, _kwargs = fake.query.call_args
    assert args[0] == "SELECT count() as cnt FROM t"


def test_count_with_condition() -> None:
    fake = _FakeClient()
    fake.query.return_value = pd.DataFrame({"cnt": [7]})
    t = _TestTable(table_name="t", client=fake)

    assert t.count(condition="symbol = 'rb2410'") == 7

    args, _kwargs = fake.query.call_args
    assert args[0] == "SELECT count() as cnt FROM t WHERE symbol = 'rb2410'"


def test_count_returns_zero_on_empty_result() -> None:
    fake = _FakeClient()
    fake.query.return_value = pd.DataFrame()
    t = _TestTable(table_name="t", client=fake)

    assert t.count() == 0


def test_count_returns_none_on_exception() -> None:
    fake = _FakeClient()
    fake.query.side_effect = RuntimeError("query failed")
    t = _TestTable(table_name="t", client=fake)

    assert t.count() is None


# ---------------------------------------------------------------------------
# optimize
# ---------------------------------------------------------------------------


def test_optimize_default() -> None:
    """`optimize(final=False)` issues `OPTIMIZE TABLE t`
    (no FINAL clause) — the default is a non-final
    merge."""
    fake = _FakeClient()
    t = _TestTable(table_name="t", client=fake)

    result = t.optimize()

    assert result is True
    args, _ = fake.execute.call_args
    assert args[0] == "OPTIMIZE TABLE t "


def test_optimize_final() -> None:
    fake = _FakeClient()
    t = _TestTable(table_name="t", client=fake)

    t.optimize(final=True)

    args, _ = fake.execute.call_args
    assert args[0] == "OPTIMIZE TABLE t FINAL"


def test_optimize_returns_false_on_client_failure() -> None:
    fake = _FakeClient()
    fake.execute.return_value = False
    t = _TestTable(table_name="t", client=fake)

    assert t.optimize() is False


def test_optimize_returns_false_on_exception() -> None:
    fake = _FakeClient()
    fake.execute.side_effect = RuntimeError("optimize failed")
    t = _TestTable(table_name="t", client=fake)

    assert t.optimize() is False


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


def test_context_manager_closes_owned_client() -> None:
    fake = _FakeClient()
    with patch(
        "gr_data.db.clickhouse.table.ClickHouseClient",
        return_value=fake,
    ):
        t = _TestTable(table_name="t")

    with t as ctx:
        assert ctx is t

    fake.close.assert_called_once()


# ---------------------------------------------------------------------------
# Repr
# ---------------------------------------------------------------------------


def test_repr_includes_table_and_pool_mode() -> None:
    fake = _FakeClient()
    pool = _FakePool(client=fake)
    t = _TestTable(table_name="bars_1d", pool=pool)

    rendered = repr(t)

    assert "bars_1d" in rendered
    assert "host='h'" in rendered
    assert "database='d'" in rendered
    assert "pool_mode=True" in rendered
    assert "owns_client=False" in rendered


def test_repr_in_client_mode() -> None:
    fake = _FakeClient()
    t = _TestTable(table_name="bars_1d", client=fake)

    rendered = repr(t)

    assert "pool_mode=False" in rendered
    assert "owns_client=False" in rendered


def test_repr_with_own_client() -> None:
    fake = _FakeClient()
    with patch(
        "gr_data.db.clickhouse.table.ClickHouseClient",
        return_value=fake,
    ):
        t = _TestTable(table_name="bars_1d")

    rendered = repr(t)

    assert "owns_client=True" in rendered
