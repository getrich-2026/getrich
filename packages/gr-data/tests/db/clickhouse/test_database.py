"""Tests for ``gr_data.db.clickhouse.database.ClickHouseClient``.

The wrapper is responsible for:
- Connection lifecycle (connect, ping, reconnect, close)
- DDL/DML via `execute()` and `execute_sql_file()`
- Read APIs (`query`, `query_sql`, `read_data`)
- Write APIs (`insert_data`, `upsert_data`)
- Schema operations (`truncate_data`, `drop_table`)
- Internal upsert routing (REPLACE INTO for
  ReplacingMergeTree, otherwise DELETE+INSERT)

These tests mock the underlying
``clickhouse_connect.get_client`` factory so no real
ClickHouse is required. The mock implements only the
methods the wrapper actually calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from gr_data.db.clickhouse.database import ClickHouseClient


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeClient:
    """In-process mock of ``clickhouse_connect.driver.client.Client``.

    Records each call. `is_connected()` returns a
    configurable bool. `ping()` can be made to raise.
    `query()` returns a configurable result wrapper. The
    `query_df` / `command` / `insert` / `insert_df` /
    `close` methods are stored as MagicMock for
    per-test assertions.
    """

    def __init__(self, *, connected: bool = True) -> None:
        self.connected = connected
        self.command = MagicMock()
        self.query = MagicMock()
        self.query_df = MagicMock()
        self.insert = MagicMock()
        self.insert_df = MagicMock()
        self.ping = MagicMock()
        self.close = MagicMock(side_effect=lambda: setattr(self, "connected", False))
        self.command_calls: list[tuple[str, dict | None]] = []
        self.query_df_calls: list[tuple[str, dict | None]] = []

        # Wire .command() and .query_df() to record inputs
        # for assertion. We do NOT wire .query() with a
        # side_effect — tests configure its `return_value`
        # directly, since the expected shape varies by
        # call site (e.g. `_support_replace_into` reads
        # `.result_rows`, `query_sql(use_df=False)` does
        # the same, etc.).
        def _command(sql, parameters=None):
            self.command_calls.append((sql, parameters))

        def _query_df(sql, parameters=None):
            self.query_df_calls.append((sql, parameters))
            return pd.DataFrame({"x": [1, 2, 3]})

        self.command.side_effect = _command
        self.query_df.side_effect = _query_df

        # Default `query()` return value: a result whose
        # `.result_rows` is an empty list. Tests that need
        # rows override `fake.query.return_value`.
        default_result = MagicMock()
        default_result.result_rows = []
        self.query.return_value = default_result

    def is_connected(self) -> bool:
        return self.connected


def _make_client() -> tuple[ClickHouseClient, _FakeClient]:
    """Build a `ClickHouseClient` whose underlying
    connection is a `_FakeClient`. Returns the wrapper
    and the fake so tests can assert on call lists."""
    fake = _FakeClient()
    with patch(
        "gr_data.db.clickhouse.database.clickhouse_connect.get_client",
        return_value=fake,
    ):
        client = ClickHouseClient(
            host="h",
            port=8123,
            user="u",
            password="p",
            database="d",
        )
    return client, fake


# ---------------------------------------------------------------------------
# Construction & connect
# ---------------------------------------------------------------------------


def test_constructor_stores_config() -> None:
    """The config dict mirrors the constructor kwargs."""
    client, _fake = _make_client()

    assert client.get_config() == {
        "host": "h",
        "port": 8123,
        "user": "u",
        "password": "p",
        "database": "d",
    }


def test_constructor_auto_connects() -> None:
    """`__init__` calls `connect()` so the wrapper is
    immediately usable. `_connection` is set to the
    fake client."""
    client, fake = _make_client()

    assert client._connection is fake
    assert client.is_connected() is True


def test_client_property_returns_underlying() -> None:
    """The `.client` property is a back-compat alias for
    `_connection` (older code paths may rely on it)."""
    client, fake = _make_client()

    assert client.client is fake


def test_get_config_returns_copy_not_reference() -> None:
    """`get_config()` returns a copy, so mutating the
    returned dict does not affect the wrapper's
    internal config."""
    client, _fake = _make_client()

    cfg = client.get_config()
    cfg["host"] = "evil"

    assert client.get_config()["host"] == "h"


# ---------------------------------------------------------------------------
# connect() / close() / is_connected() / ensure_connection()
# ---------------------------------------------------------------------------


def test_connect_pings_existing_connection() -> None:
    """If a connection is already set, `connect()` pings
    it to confirm liveness. A successful ping keeps the
    connection (no new client created)."""
    client, fake = _make_client()

    # Pre-seed the client property to spy on a fresh
    # clickhouse_connect.get_client call.
    with patch("gr_data.db.clickhouse.database.clickhouse_connect.get_client") as factory:
        result = client.connect()
        factory.assert_not_called()
        fake.ping.assert_called_once()

    assert result is True


def test_connect_reconnects_when_ping_fails() -> None:
    """If the existing connection's ping raises, the
    wrapper drops it and creates a fresh one."""
    client, fake = _make_client()
    fake.ping.side_effect = RuntimeError("ping failed")

    fresh = _FakeClient()
    with patch(
        "gr_data.db.clickhouse.database.clickhouse_connect.get_client",
        return_value=fresh,
    ) as factory:
        result = client.connect()

    assert result is True
    assert client._connection is fresh
    factory.assert_called_once()


def test_connect_returns_false_when_factory_raises() -> None:
    """If `get_client(...)` raises, the wrapper swallows
    the error, clears the connection, and returns False."""
    client, _fake = _make_client()
    client._connection = None

    with patch(
        "gr_data.db.clickhouse.database.clickhouse_connect.get_client",
        side_effect=RuntimeError("connect failed"),
    ):
        result = client.connect()

    assert result is False
    assert client._connection is None


def test_is_connected_reflects_internal_state() -> None:
    client, fake = _make_client()
    assert client.is_connected() is True

    client._connection = None
    assert client.is_connected() is False

    # Restore for close() test
    client._connection = fake


def test_close_closes_underlying() -> None:
    client, fake = _make_client()

    client.close()

    fake.close.assert_called_once()
    assert client._connection is None


def test_close_is_safe_when_already_disconnected() -> None:
    client, _fake = _make_client()
    client._connection = None  # already gone

    client.close()  # must not raise


def test_close_swallows_underlying_error() -> None:
    """If `client.close()` raises, the wrapper catches
    the error and logs it. Crucially, `_connection` is
    cleared BEFORE the underlying `close()` call, so a
    failed close() still leaves the wrapper in the
    "no connection" state — the next `connect()` will
    not waste a `ping()` round-trip on a known-dead
    connection object."""
    client, fake = _make_client()
    fake.close.side_effect = RuntimeError("close failed")

    client.close()  # should not raise

    fake.close.assert_called_once()
    # The dead connection is gone from the wrapper's slot.
    assert client._connection is None


def test_close_clears_connection_before_close_so_next_connect_skips_ping() -> None:
    """Regression: if `close()` raises, the next `connect()`
    call must NOT call `ping()` on a known-dead object. The
    wrapper clears `self._connection` BEFORE calling
    `close()`, so `connect()` sees None and goes straight to
    `get_client()`."""
    client, fake = _make_client()
    fake.close.side_effect = RuntimeError("close failed")

    # First close (fails inside, _connection is None now).
    client.close()
    assert client._connection is None

    # Simulate a new connection being established.
    new_fake = _FakeClient(connected=True)
    with patch(
        "gr_data.db.clickhouse.database.clickhouse_connect.get_client",
        return_value=new_fake,
    ):
        # The new client's ping must NOT have been called.
        new_fake.ping.reset_mock()
        client.connect()

    # The new connection was wired up. `ping()` was NOT
    # called during `connect()` because `_connection` was
    # already None when we entered connect().
    new_fake.ping.assert_not_called()
    assert client._connection is new_fake


def test_ensure_connection_returns_true_when_already_connected() -> None:
    client, _fake = _make_client()

    assert client.ensure_connection() is True


def test_ensure_connection_reconnects_when_disconnected() -> None:
    client, _fake = _make_client()
    client._connection = None

    fresh = _FakeClient()
    with patch(
        "gr_data.db.clickhouse.database.clickhouse_connect.get_client",
        return_value=fresh,
    ):
        result = client.ensure_connection()

    assert result is True
    assert client._connection is fresh


def test_ensure_connection_returns_false_when_reconnect_fails() -> None:
    client, _fake = _make_client()
    client._connection = None

    with patch(
        "gr_data.db.clickhouse.database.clickhouse_connect.get_client",
        side_effect=RuntimeError("nope"),
    ):
        result = client.ensure_connection()

    assert result is False


# ---------------------------------------------------------------------------
# configure()
# ---------------------------------------------------------------------------


def test_configure_updates_individual_fields() -> None:
    client, _fake = _make_client()

    client.configure(host="new.host", port=9999, reconnect=False)

    assert client.get_config()["host"] == "new.host"
    assert client.get_config()["port"] == 9999


def test_configure_skips_none_values() -> None:
    """`configure()` is partial-update: passing None for
    a field leaves it untouched."""
    client, _fake = _make_client()

    client.configure(host="only.host", reconnect=False)

    assert client.get_config()["host"] == "only.host"
    assert client.get_config()["port"] == 8123  # unchanged
    assert client.get_config()["user"] == "u"  # unchanged


def test_configure_reconnects_by_default() -> None:
    """`reconnect=True` (the default) closes the existing
    connection and creates a fresh one."""
    client, old_fake = _make_client()

    fresh = _FakeClient()
    with patch(
        "gr_data.db.clickhouse.database.clickhouse_connect.get_client",
        return_value=fresh,
    ):
        client.configure(host="new.host")  # reconnect=True default

    old_fake.close.assert_called_once()
    assert client._connection is fresh


def test_configure_reconnect_false_keeps_connection() -> None:
    """`reconnect=False` updates the config but does NOT
    close/reconnect. The next query will hit the old
    connection with the new (now stale) config — that
    is the caller's responsibility."""
    client, old_fake = _make_client()

    client.configure(host="new.host", reconnect=False)

    assert client._connection is old_fake
    assert client.get_config()["host"] == "new.host"


# ---------------------------------------------------------------------------
# execute()
# ---------------------------------------------------------------------------


def test_execute_runs_command_with_no_params() -> None:
    client, fake = _make_client()

    result = client.execute("CREATE TABLE t (x Int32)")

    assert result is True
    assert len(fake.command_calls) == 1
    sql, params = fake.command_calls[0]
    assert sql == "CREATE TABLE t (x Int32)"
    assert params is None


def test_execute_runs_command_with_params() -> None:
    client, fake = _make_client()

    result = client.execute("INSERT INTO t VALUES", {"x": 1})

    assert result is True
    sql, params = fake.command_calls[0]
    assert params == {"x": 1}


def test_execute_returns_false_on_error_and_drops_connection() -> None:
    """A failed `command` returns False AND sets
    `_connection = None` so the next call triggers a
    reconnect. (This is the wrapper's self-healing
    pattern.)"""
    client, fake = _make_client()
    fake.command.side_effect = RuntimeError("server gone")

    result = client.execute("SELECT 1")

    assert result is False
    assert client._connection is None


def test_execute_returns_false_when_ensure_connection_fails() -> None:
    client, _fake = _make_client()
    client._connection = None

    with patch(
        "gr_data.db.clickhouse.database.clickhouse_connect.get_client",
        side_effect=RuntimeError("nope"),
    ):
        result = client.execute("SELECT 1")

    assert result is False


# ---------------------------------------------------------------------------
# execute_sql_file()
# ---------------------------------------------------------------------------


def test_execute_sql_file_runs_all_statements(tmp_path) -> None:
    """`execute_sql_file()` splits on `;`, skips
    comment-only statements, and runs the rest."""
    client, fake = _make_client()

    sql_file = tmp_path / "schema.sql"
    sql_file.write_text(
        "-- header comment\n"
        "CREATE TABLE t1 (x Int32);\n"
        "-- another comment\n"
        "CREATE TABLE t2 (y Int32);\n",
        encoding="utf-8",
    )

    result = client.execute_sql_file(str(sql_file))

    assert result is True
    # 2 actual statements executed (the comments are skipped).
    assert len(fake.command_calls) == 2
    assert "CREATE TABLE t1" in fake.command_calls[0][0]
    assert "CREATE TABLE t2" in fake.command_calls[1][0]


def test_execute_sql_file_stops_on_first_failure(tmp_path) -> None:
    """If any statement fails, `execute_sql_file` aborts
    and returns False. The third statement is never run."""
    client, fake = _make_client()
    call_count = {"n": 0}

    def _maybe_fail(sql, parameters=None):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("schema mismatch")

    fake.command.side_effect = _maybe_fail

    sql_file = tmp_path / "schema.sql"
    sql_file.write_text(
        "CREATE TABLE a (x Int32);\nCREATE TABLE b (y Int32);\nCREATE TABLE c (z Int32);\n",
        encoding="utf-8",
    )

    result = client.execute_sql_file(str(sql_file))

    assert result is False
    assert call_count["n"] == 2  # stopped at the 2nd


def test_execute_sql_file_handles_missing_file(tmp_path) -> None:
    client, _fake = _make_client()

    result = client.execute_sql_file(str(tmp_path / "missing.sql"))

    assert result is False


def test_execute_sql_file_with_empty_file(tmp_path) -> None:
    """A file with no statements (only whitespace /
    comments) is a no-op — the wrapper returns True."""
    client, fake = _make_client()

    sql_file = tmp_path / "empty.sql"
    sql_file.write_text("-- only a comment\n", encoding="utf-8")

    result = client.execute_sql_file(str(sql_file))

    assert result is True
    assert fake.command_calls == []


# ---------------------------------------------------------------------------
# query() / query_sql() / read_data()
# ---------------------------------------------------------------------------


def test_query_returns_dataframe() -> None:
    client, fake = _make_client()

    result = client.query("SELECT * FROM t")

    assert isinstance(result, pd.DataFrame)
    assert list(result["x"]) == [1, 2, 3]
    assert len(fake.query_df_calls) == 1


def test_query_returns_empty_dataframe_on_error() -> None:
    client, fake = _make_client()
    fake.query_df.side_effect = RuntimeError("query failed")

    result = client.query("SELECT * FROM bogus")

    assert isinstance(result, pd.DataFrame)
    assert result.empty
    assert client._connection is None  # dropped


def test_query_returns_empty_when_ensure_fails() -> None:
    client, _fake = _make_client()
    client._connection = None

    with patch(
        "gr_data.db.clickhouse.database.clickhouse_connect.get_client",
        side_effect=RuntimeError("nope"),
    ):
        result = client.query("SELECT 1")

    assert result.empty


def test_query_forwards_params() -> None:
    client, fake = _make_client()

    client.query("SELECT * FROM t WHERE x = %(x)s", {"x": 42})

    sql, params = fake.query_df_calls[0]
    assert params == {"x": 42}


def test_query_sql_dataframe_mode() -> None:
    client, fake = _make_client()

    result = client.query_sql("SELECT * FROM t", use_df=True)

    assert isinstance(result, pd.DataFrame)
    assert len(fake.query_df_calls) == 1


def test_query_sql_list_mode() -> None:
    """`use_df=False` returns `result.result_rows` (a
    list-of-lists) instead of a DataFrame."""
    client, fake = _make_client()
    result_mock = MagicMock()
    result_mock.result_rows = [["row1"], ["row2"]]
    fake.query.return_value = result_mock

    result = client.query_sql("SELECT * FROM t", use_df=False)

    assert result == [["row1"], ["row2"]]
    assert len(fake.query_df_calls) == 0


def test_query_sql_returns_none_on_error() -> None:
    client, fake = _make_client()
    fake.query_df.side_effect = RuntimeError("fail")

    result = client.query_sql("SELECT bogus", use_df=True)

    assert result is None


def test_read_data_builds_select_with_clauses() -> None:
    """`read_data()` concatenates the optional WHERE /
    ORDER BY / LIMIT / OFFSET clauses into a single
    SELECT statement."""
    client, fake = _make_client()

    result = client.read_data(
        table_name="bars",
        columns="symbol, close",
        condition="symbol = 'rb2410'",
        limit=10,
        offset=20,
        order_by="dt DESC",
    )

    sql, params = fake.query_df_calls[0]
    assert "SELECT symbol, close FROM bars" in sql
    assert "WHERE symbol = 'rb2410'" in sql
    assert "ORDER BY dt DESC" in sql
    assert "LIMIT 10" in sql
    assert "OFFSET 20" in sql
    assert isinstance(result, pd.DataFrame)


def test_read_data_no_clauses_minimal_select() -> None:
    client, fake = _make_client()

    client.read_data(table_name="t")

    sql, params = fake.query_df_calls[0]
    assert sql == "SELECT * FROM t"
    assert params is None


def test_read_data_forwards_explicit_params() -> None:
    """`params` is passed through to `query_df` only when
    the caller supplies it (the wrapper's `if params:`
    branch). When omitted, `query_df` is called without
    a parameters kwarg."""
    client, fake = _make_client()

    client.read_data(table_name="t", condition="x = %(x)s", params={"x": 1})

    sql, params = fake.query_df_calls[0]
    assert params == {"x": 1}


def test_read_data_returns_none_on_error() -> None:
    client, fake = _make_client()
    fake.query_df.side_effect = RuntimeError("read failed")

    result = client.read_data(table_name="t")

    assert result is None
    assert client._connection is None


# ---------------------------------------------------------------------------
# insert_data()
# ---------------------------------------------------------------------------


def test_insert_dataframe_single_call_when_no_batches() -> None:
    """A small DataFrame (smaller than `batch_size`) is
    inserted in a single `insert_df` call."""
    client, fake = _make_client()
    df = pd.DataFrame({"a": [1, 2, 3]})

    result = client.insert_data("t", df)

    assert result is True
    fake.insert_df.assert_called_once()
    args, _kwargs = fake.insert_df.call_args
    assert args[0] == "t"
    pd.testing.assert_frame_equal(args[1], df)


def test_insert_dataframe_batches_when_size_exceeds_batch_size() -> None:
    """With `batch_size=2` and 5 rows, the wrapper makes
    3 calls to `insert_df` (2 + 2 + 1)."""
    client, fake = _make_client()
    df = pd.DataFrame({"a": [1, 2, 3, 4, 5]})

    result = client.insert_data("t", df, batch_size=2)

    assert result is True
    assert fake.insert_df.call_count == 3
    # Last batch has 1 row (the leftover).
    last_args, _ = fake.insert_df.call_args_list[-1]
    assert len(last_args[1]) == 1


def test_insert_empty_dataframe_is_noop() -> None:
    client, fake = _make_client()

    result = client.insert_data("t", pd.DataFrame())

    assert result is True
    fake.insert_df.assert_not_called()


def test_insert_list_requires_column_names() -> None:
    """List-mode without `column_names` is rejected — the
    wrapper cannot otherwise build a valid INSERT."""
    client, fake = _make_client()

    result = client.insert_data("t", [[1, "a"], [2, "b"]])

    assert result is False
    fake.insert.assert_not_called()


def test_insert_list_single_call() -> None:
    client, fake = _make_client()

    result = client.insert_data(
        "t",
        [[1, "a"], [2, "b"]],
        column_names=["id", "name"],
    )

    assert result is True
    fake.insert.assert_called_once()
    args, kwargs = fake.insert.call_args
    assert args[0] == "t"
    assert args[1] == [[1, "a"], [2, "b"]]
    # `column_names` is passed as a keyword arg.
    assert kwargs["column_names"] == ["id", "name"]


def test_insert_list_batches() -> None:
    client, fake = _make_client()

    rows = [[i, f"row{i}"] for i in range(5)]
    result = client.insert_data("t", rows, column_names=["id", "name"], batch_size=2)

    assert result is True
    assert fake.insert.call_count == 3
    last_args, _ = fake.insert.call_args_list[-1]
    assert len(last_args[1]) == 1


def test_insert_empty_list_warns_and_returns_false() -> None:
    client, fake = _make_client()

    result = client.insert_data("t", [], column_names=["id"])

    assert result is False
    fake.insert.assert_not_called()


def test_insert_unsupported_type_returns_false() -> None:
    """A type that's neither DataFrame nor list is
    rejected (e.g. a dict or string)."""
    client, fake = _make_client()

    result = client.insert_data("t", "not a table")  # type: ignore[arg-type]

    assert result is False


def test_insert_returns_false_when_ensure_fails() -> None:
    client, _fake = _make_client()
    client._connection = None

    with patch(
        "gr_data.db.clickhouse.database.clickhouse_connect.get_client",
        side_effect=RuntimeError("nope"),
    ):
        result = client.insert_data("t", pd.DataFrame({"a": [1]}))

    assert result is False


def test_insert_dataframe_inner_error_returns_false() -> None:
    """If `insert_df` raises, the wrapper returns False
    (the inner except block catches it). The outer
    except is for the connection-loss case."""
    client, fake = _make_client()
    fake.insert_df.side_effect = RuntimeError("disk full")

    result = client.insert_data("t", pd.DataFrame({"a": [1]}))

    assert result is False


# ---------------------------------------------------------------------------
# upsert_data() — key columns check
# ---------------------------------------------------------------------------


def test_upsert_data_rejects_non_dataframe() -> None:
    client, _fake = _make_client()

    result = client.upsert_data("t", [[1, 2]], key_columns=["id"])  # type: ignore[arg-type]

    assert result is False


def test_upsert_data_rejects_empty_dataframe() -> None:
    client, _fake = _make_client()

    result = client.upsert_data("t", pd.DataFrame(), key_columns=["id"])

    assert result is False


def test_upsert_data_rejects_missing_key_columns() -> None:
    """If any `key_columns` entry is not in the DataFrame's
    columns, the wrapper rejects the call (early — no
    network traffic)."""
    client, _fake = _make_client()
    df = pd.DataFrame({"a": [1, 2]})

    result = client.upsert_data("t", df, key_columns=["a", "b"])

    assert result is False


def test_upsert_data_single_batch_routes_to_insert() -> None:
    """With `batch_size=None` and small data, the wrapper
    calls `_process_upsert_batch` once (which delegates
    to `insert_data` when ReplacingMergeTree is detected,
    or DELETE+INSERT otherwise)."""
    client, fake = _make_client()
    df = pd.DataFrame({"id": [1, 2], "v": [10, 20]})

    with patch.object(
        client,
        "_support_replace_into",
        return_value=True,
    ):
        result = client.upsert_data("t", df, key_columns=["id"])

    assert result is True
    # insert_df was called once (via insert_data → _upsert_with_replace).
    fake.insert_df.assert_called_once()


def test_upsert_data_multi_batch_stops_on_failure() -> None:
    """With `batch_size=2` and 4 rows, processing happens
    in 2 batches. If the 2nd batch fails, the wrapper
    returns False (no further processing)."""
    client, fake = _make_client()
    df = pd.DataFrame({"id": [1, 2, 3, 4], "v": [10, 20, 30, 40]})
    call_count = {"n": 0}

    def _maybe_fail(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("batch 2 failed")

    fake.insert_df.side_effect = _maybe_fail

    with patch.object(client, "_support_replace_into", return_value=True):
        result = client.upsert_data("t", df, key_columns=["id"], batch_size=2)

    assert result is False
    assert call_count["n"] == 2


def test_upsert_data_returns_false_when_ensure_fails() -> None:
    client, _fake = _make_client()
    client._connection = None

    with patch(
        "gr_data.db.clickhouse.database.clickhouse_connect.get_client",
        side_effect=RuntimeError("nope"),
    ):
        result = client.upsert_data("t", pd.DataFrame({"id": [1]}), key_columns=["id"])

    assert result is False


# ---------------------------------------------------------------------------
# _support_replace_into() — engine detection
# ---------------------------------------------------------------------------


def test_support_replace_into_returns_false_for_empty_result() -> None:
    """If the `system.tables` query returns no rows
    (table does not exist), the wrapper assumes
    REPLACE INTO is not supported."""
    client, fake = _make_client()
    result_mock = MagicMock()
    result_mock.result_rows = []
    fake.query.return_value = result_mock

    assert client._support_replace_into("nonexistent") is False


def test_support_replace_into_true_for_replacing_merge_tree() -> None:
    client, fake = _make_client()
    result_mock = MagicMock()
    result_mock.result_rows = [("ReplacingMergeTree", "id")]
    fake.query.return_value = result_mock

    assert client._support_replace_into("t") is True


def test_support_replace_into_true_for_table_with_primary_key() -> None:
    """Any table with a non-empty `primary_key` is
    considered REPLACE-INTO capable, even if the engine
    is plain MergeTree (REPLACE INTO needs an ORDER BY
    column, which the primary key satisfies)."""
    client, fake = _make_client()
    result_mock = MagicMock()
    result_mock.result_rows = [("MergeTree", "id")]
    fake.query.return_value = result_mock

    assert client._support_replace_into("t") is True


def test_support_replace_into_false_for_no_primary_key_merge_tree() -> None:
    client, fake = _make_client()
    result_mock = MagicMock()
    result_mock.result_rows = [("MergeTree", "")]
    fake.query.return_value = result_mock

    assert client._support_replace_into("t") is False


def test_support_replace_into_returns_false_on_error() -> None:
    """If the engine-detection query raises, fall back
    to the conservative (False) path: the upsert
    proceeds via DELETE+INSERT instead of REPLACE INTO."""
    client, fake = _make_client()
    fake.query.side_effect = RuntimeError("system query failed")

    assert client._support_replace_into("t") is False


def test_support_replace_into_returns_false_when_disconnected() -> None:
    client, _fake = _make_client()
    client._connection = None

    assert client._support_replace_into("t") is False


# ---------------------------------------------------------------------------
# _delete_existing_records() — IN-clause builder
# ---------------------------------------------------------------------------


def test_delete_existing_records_single_string_column() -> None:
    """For a single string-typed key column, the
    IN-clause values are quoted and single-quote-escaped
    (`'` → `''`)."""
    client, fake = _make_client()
    df = pd.DataFrame({"symbol": ["rb2410", "cu2412"]})

    result = client._delete_existing_records("t", df, ["symbol"])

    assert result is True
    # Two DELETE statements: one per 500-key batch.
    assert len(fake.command_calls) == 1
    sql, _ = fake.command_calls[0]
    assert "ALTER TABLE t DELETE WHERE" in sql
    assert "'rb2410'" in sql
    assert "'cu2412'" in sql
    # The escaping for the apostrophe in the test data is
    # exercised by the `replace("'", "''")` call in the
    # wrapper — it doesn't fire here (no apostrophe in
    # "rb2410") but the formatter is in the call path.


def test_delete_existing_records_single_int_column() -> None:
    """For a single int-typed key column, the IN-clause
    values are NOT quoted (numeric literals)."""
    client, fake = _make_client()
    df = pd.DataFrame({"id": [10, 20, 30]})

    result = client._delete_existing_records("t", df, ["id"])

    assert result is True
    sql, _ = fake.command_calls[0]
    assert "10" in sql
    assert "20" in sql
    assert "30" in sql


def test_delete_existing_records_multi_column() -> None:
    """For multi-column keys, the wrapper builds
    `((c1 = v1) AND (c2 = v2)) OR (...)` predicates."""
    client, fake = _make_client()
    df = pd.DataFrame(
        {
            "symbol": ["rb2410", "cu2412"],
            "dt": ["2024-01-01", "2024-01-02"],
        }
    )

    result = client._delete_existing_records("t", df, ["symbol", "dt"])

    assert result is True
    sql, _ = fake.command_calls[0]
    assert "(symbol = 'rb2410' AND dt = '2024-01-01')" in sql
    assert "(symbol = 'cu2412' AND dt = '2024-01-02')" in sql
    assert " OR " in sql


def test_delete_existing_records_handles_null_in_multi_column() -> None:
    """In multi-column mode, NaN values become
    `IS NULL` clauses (rather than `= NULL` which is
    always false in SQL)."""
    client, fake = _make_client()
    df = pd.DataFrame(
        {
            "a": [1, 2],
            "b": [None, "x"],
        }
    )

    result = client._delete_existing_records("t", df, ["a", "b"])

    assert result is True
    sql, _ = fake.command_calls[0]
    # The NaN row becomes `(a = 1 AND b IS NULL)`.
    assert "b IS NULL" in sql


def test_delete_existing_records_batches_at_500_keys() -> None:
    """The wrapper partitions keys into batches of 500
    to avoid IN-clause length explosions."""
    client, fake = _make_client()
    df = pd.DataFrame({"id": list(range(1200))})

    result = client._delete_existing_records("t", df, ["id"])

    assert result is True
    # 1200 / 500 = 3 batches (500, 500, 200).
    assert len(fake.command_calls) == 3


def test_delete_existing_records_returns_false_on_alter_failure() -> None:
    """P0 fix (Round #1047): previously `_delete_existing_records`
    IGNORED the return value of `self.execute(delete_query)` —
    so a single failing ALTER batch would silently leave the
    upsert pipeline to insert NEW rows on top of un-deleted OLD
    rows. After the fix, the method short-circuits to `False`
    on the first failed batch, giving the caller a chance to
    abort.

    The failure mode in production is `command()` raising
    (network error, permission denied, etc.), which `execute()`
    catches and turns into `False`. We mirror that here by
    raising from the side_effect."""
    client, fake = _make_client()
    calls: list[tuple[str, dict | None]] = []

    def _record_and_fail(sql, parameters=None):
        calls.append((sql, parameters))
        raise RuntimeError("ALTER failed (table missing)")

    fake.command.side_effect = _record_and_fail
    df = pd.DataFrame({"id": [1]})

    result = client._delete_existing_records("t", df, ["id"])

    assert result is False
    assert len(calls) == 1
    assert "ALTER TABLE t DELETE WHERE" in calls[0][0]


def test_delete_existing_records_stops_at_first_failing_batch() -> None:
    """With 1200 keys (3 batches of 500), if batch #2 fails
    the method returns False AND batch #3 is never attempted."""
    client, fake = _make_client()
    call_count = {"n": 0}

    def _fail_on_second(sql, parameters=None):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("ALTER failed (batch 2)")
        return None

    fake.command.side_effect = _fail_on_second
    df = pd.DataFrame({"id": list(range(1200))})

    result = client._delete_existing_records("t", df, ["id"])

    assert result is False
    assert call_count["n"] == 2  # stopped at batch 2; #3 was never attempted


def test_delete_existing_records_all_batches_succeed() -> None:
    """Sanity check: with 1200 keys, if all 3 batches succeed
    the method returns True."""
    client, fake = _make_client()
    df = pd.DataFrame({"id": list(range(1200))})

    result = client._delete_existing_records("t", df, ["id"])

    assert result is True
    # 3 batches (500, 500, 200).
    assert len(fake.command_calls) == 3


def test_upsert_with_delete_insert_aborts_when_delete_fails() -> None:
    """Caller-level P0: when `_delete_existing_records`
    returns False (e.g. ALTER failed), `_upsert_with_delete_insert`
    MUST NOT proceed to `insert_data` — otherwise we'd have
    duplicate rows (old + new) on top of the failed DELETE.

    Before Round #1047, this was a silent-failure risk: the
    INSERT would proceed and the caller (`upsert_data`) would
    return True, reporting success while leaving the table in
    an inconsistent state."""
    client, fake = _make_client()

    # Force the DELETE path (not REPLACE INTO) by reporting
    # the table as plain MergeTree with no primary key.
    result_mock = MagicMock()
    result_mock.result_rows = [("MergeTree", "")]
    fake.query.return_value = result_mock

    # Make the underlying command() raise → execute() → False
    # → _delete_existing_records → False → caller aborts.
    fake.command.side_effect = RuntimeError("ALTER failed")

    df = pd.DataFrame({"id": [1, 2]})
    result = client.upsert_data("t", df, key_columns=["id"])

    assert result is False
    # `insert_data` must NOT have been called (no insert_df calls).
    fake.insert_df.assert_not_called()
    fake.insert.assert_not_called()


def test_delete_existing_records_returns_false_on_outside_error() -> None:
    """An error during the DataFrame prep (NOT during
    the SQL execution) propagates as `False`."""
    client, fake = _make_client()
    # A DataFrame without the requested key column
    # raises `KeyError` inside `data[key_columns]` —
    # which is OUTSIDE of the `execute()` call.
    df = pd.DataFrame({"unrelated": [1]})

    result = client._delete_existing_records("t", df, ["id"])

    assert result is False


# ---------------------------------------------------------------------------
# truncate_data() / drop_table()
# ---------------------------------------------------------------------------


def test_truncate_data_runs_truncate_sql() -> None:
    client, fake = _make_client()

    result = client.truncate_data("t")

    assert result is True
    sql, _ = fake.command_calls[0]
    assert sql == "TRUNCATE TABLE t"


def test_truncate_data_returns_false_on_error() -> None:
    client, fake = _make_client()
    fake.command.side_effect = RuntimeError("truncate failed")

    result = client.truncate_data("t")

    assert result is False


def test_drop_table_with_if_exists() -> None:
    client, fake = _make_client()

    result = client.drop_table("t", if_exists=True)

    assert result is True
    sql, _ = fake.command_calls[0]
    assert "DROP TABLE IF EXISTS t" in sql


def test_drop_table_without_if_exists() -> None:
    client, fake = _make_client()

    result = client.drop_table("t", if_exists=False)

    assert result is True
    sql, _ = fake.command_calls[0]
    # No `IF EXISTS` clause.
    assert sql == "DROP TABLE  t"


# ---------------------------------------------------------------------------
# Context manager / repr
# ---------------------------------------------------------------------------


def test_context_manager_closes_on_exit() -> None:
    client, fake = _make_client()

    with client as c:
        assert c is client

    fake.close.assert_called_once()
    assert client._connection is None


def test_repr_includes_host_database_connected() -> None:
    client, _fake = _make_client()

    rendered = repr(client)

    assert "host='h'" in rendered
    assert "database='d'" in rendered
    assert "connected=True" in rendered
