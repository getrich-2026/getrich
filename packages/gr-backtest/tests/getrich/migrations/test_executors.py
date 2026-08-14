"""Tests for ``getrich.migrations.executors``.

The executors are the bridge between the pure-Python
runner and a real database. Two implementations:

- ``PostgresMigrationExecutor`` — sync :mod:`psycopg` v3
  connection, per-migration transaction with rollback
  on failure.
- ``ClickHouseMigrationExecutor`` — :mod:`clickhouse_connect`
  client, per-statement (no classical transactions).

Both implement the same 3-method protocol
(``ensure_tracking_table`` / ``fetch_applied`` / ``apply_one``)
that the runner calls. We test by injecting fake
connections / clients and asserting on the SQL that was
emitted, the cursor commit/rollback calls, and the bookkeeping
INSERTs.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from getrich.migrations.executors import (
    ClickHouseMigrationExecutor,
    PostgresMigrationExecutor,
)
from getrich.migrations.runner import Migration, MigrationError


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeCursor:
    """In-process psycopg cursor fake.

    Records each `execute()` call. `fetchall()` returns a
    configurable list of row tuples.
    """

    def __init__(self, fetchall_rows: list[tuple] | None = None) -> None:
        self.executed: list[tuple[str, Any]] = []
        self._fetchall = fetchall_rows or []
        self.entered = False
        self.exited = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *args):
        self.exited = True
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return self._fetchall


class _FakeConn:
    """In-process psycopg connection fake.

    `cursor()` returns a fresh `_FakeCursor` per call (the real
    cursor is a context manager). `commit()` / `rollback()`
    are recorded. By default, a NEW cursor is created per
    `cursor()` call; tests that need to inject a raising
    cursor can call `script_next_cursor(...)` to control
    the next emission.
    """

    def __init__(self, fetchall_rows: list[tuple] | None = None) -> None:
        self.cursors: list[_FakeCursor] = []
        self._fetchall_rows = fetchall_rows
        self._next_cursor: _FakeCursor | None = None
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> _FakeCursor:
        if self._next_cursor is not None:
            cur = self._next_cursor
            self._next_cursor = None
        else:
            cur = _FakeCursor(fetchall_rows=self._fetchall_rows)
        self.cursors.append(cur)
        return cur

    def script_next_cursor(self, cur: _FakeCursor) -> None:
        """Inject a specific cursor to be returned by the
        NEXT call to `cursor()`. Used to make a cursor raise."""
        self._next_cursor = cur

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


# ---------------------------------------------------------------------------
# PostgresMigrationExecutor
# ---------------------------------------------------------------------------


def test_postgres_constructor_sets_search_path() -> None:
    """The executor pins `search_path=frontend` on construction
    so subsequent migration SQL (which doesn't qualify schema
    names) resolves against the right schema."""
    conn = _FakeConn()
    PostgresMigrationExecutor(conn)

    # The constructor runs a `SET search_path TO frontend` cursor.
    assert len(conn.cursors) == 1
    cur = conn.cursors[0]
    assert cur.executed[0][0] == "SET search_path TO frontend"


def test_postgres_ensure_tracking_table_creates_schema_migrations() -> None:
    """`ensure_tracking_table()` runs the tracking-table DDL
    and commits. The DDL must be `CREATE TABLE IF NOT EXISTS`
    so re-runs are safe."""
    conn = _FakeConn()
    exe = PostgresMigrationExecutor(conn)

    _run(exe.ensure_tracking_table())

    # Constructor's cursor (0) + ensure's cursor (1).
    assert len(conn.cursors) == 2
    cur = conn.cursors[1]
    ddl = cur.executed[0][0]
    assert "CREATE TABLE IF NOT EXISTS schema_migrations" in ddl
    assert "PRIMARY KEY" in ddl
    assert conn.commits == 1


def test_postgres_fetch_applied_returns_prefix_set() -> None:
    """`fetch_applied()` reads the `prefix` column of the
    tracking table and returns the set of applied prefixes."""
    conn = _FakeConn(fetchall_rows=[("001",), ("002",), ("010",)])
    exe = PostgresMigrationExecutor(conn)

    applied = _run(exe.fetch_applied())

    assert applied == {"001", "002", "010"}
    # The SQL is the simple `SELECT prefix` projection.
    # (cursor[0] is the constructor's SET search_path.)
    sql = conn.cursors[1].executed[0][0]
    assert sql == "SELECT prefix FROM schema_migrations"


def test_postgres_fetch_applied_empty_returns_empty_set() -> None:
    """Fresh DB: no rows in the tracking table → empty set
    (the runner then plans to apply EVERY discovered
    migration)."""
    conn = _FakeConn(fetchall_rows=[])
    exe = PostgresMigrationExecutor(conn)

    applied = _run(exe.fetch_applied())

    assert applied == set()


def test_postgres_apply_one_runs_sql_then_books() -> None:
    """`apply_one()` runs the migration SQL, then INSERTs
    a bookkeeping row with the migration's prefix and name.
    Both happen inside one transaction (single commit)."""
    conn = _FakeConn()
    exe = PostgresMigrationExecutor(conn)
    migration = Migration(
        prefix="005",
        name="add_users",
        path=Path("005_add_users.sql"),
        sql="CREATE TABLE users (id INT);",
    )

    _run(exe.apply_one(migration))

    # 3 cursors: constructor (SET), migration SQL, bookkeeping.
    assert len(conn.cursors) == 3
    sql_cur, book_cur = conn.cursors[1], conn.cursors[2]
    assert sql_cur.executed[0][0] == "CREATE TABLE users (id INT);"
    insert_sql, insert_params = book_cur.executed[0]
    assert "INSERT INTO schema_migrations" in insert_sql
    assert insert_params == ("005", "add_users")
    # Single commit covers both statements.
    assert conn.commits == 1
    assert conn.rollbacks == 0


def test_postgres_apply_one_rolls_back_on_sql_error() -> None:
    """If the migration SQL raises, the executor rolls back
    the (partial) transaction AND raises `MigrationError`
    with the migration's name. The connection is left in a
    usable state (no half-applied migration + half-applied
    bookkeeping)."""
    conn = _FakeConn()
    exe = PostgresMigrationExecutor(conn)
    migration = Migration(
        prefix="006",
        name="broken",
        path=Path("006_broken.sql"),
        sql="BAD SQL",
    )

    # Inject a cursor that raises on execute() — the
    # SECOND cursor (after the constructor's SET) is the
    # migration SQL cursor.
    raising = _FakeCursor()

    def _raise(_sql, params=None):
        raise RuntimeError("syntax error at end of input")

    raising.execute = _raise  # type: ignore[method-assign]
    conn.script_next_cursor(raising)

    with pytest.raises(MigrationError) as exc_info:
        _run(exe.apply_one(migration))

    assert "broken" in str(exc_info.value)
    assert "syntax error" in str(exc_info.value)
    assert conn.rollbacks == 1
    assert conn.commits == 0


def test_postgres_apply_one_rolls_back_on_bookkeeping_error() -> None:
    """A failure on the bookkeeping INSERT (e.g. duplicate
    prefix) also rolls back the whole transaction — the
    migration SQL is UNDONE in this case. (PostgreSQL doesn't
    have nested transactions unless we use SAVEPOINTs.)"""
    conn = _FakeConn()
    exe = PostgresMigrationExecutor(conn)
    migration = Migration(
        prefix="007",
        name="dup_prefix",
        path=Path("007_dup_prefix.sql"),
        sql="CREATE TABLE t (x INT);",
    )

    # First extra cursor (migration SQL) succeeds. Second extra
    # cursor (bookkeeping) raises.
    good = _FakeCursor()
    good.executed.append(("CREATE TABLE t (x INT);", None))  # pretend it ran

    bad = _FakeCursor()

    def _raise(_sql, params=None):
        raise RuntimeError("duplicate key value violates unique constraint")

    bad.execute = _raise  # type: ignore[method-assign]
    conn.script_next_cursor(good)
    conn.script_next_cursor(bad)

    with pytest.raises(MigrationError):
        _run(exe.apply_one(migration))

    assert conn.rollbacks == 1
    assert conn.commits == 0


# ---------------------------------------------------------------------------
# ClickHouseMigrationExecutor
# ---------------------------------------------------------------------------


def test_clickhouse_ensure_tracking_table_uses_merge_tree() -> None:
    """The ClickHouse tracking table uses `MergeTree` (not
    ReplacingMergeTree) — bookkeeping is append-only, so a
    `FINAL` SELECT dedup suffices and there's no need for the
    version-aware engine."""
    client = MagicMock()
    exe = ClickHouseMigrationExecutor(client)

    _run(exe.ensure_tracking_table())

    # `command` is called with the DDL.
    client.command.assert_called_once()
    ddl = client.command.call_args[0][0]
    assert "CREATE TABLE IF NOT EXISTS schema_migrations" in ddl
    assert "ENGINE = MergeTree()" in ddl
    assert "ORDER BY prefix" in ddl


def test_clickhouse_fetch_applied_uses_final_keyword() -> None:
    """ClickHouse doesn't enforce uniqueness on MergeTree, so
    the executor must use `SELECT ... FINAL` to dedup any
    duplicates that may have been inserted by a prior run."""
    client = MagicMock()
    result = MagicMock()
    result.result_rows = [("001",), ("002",)]
    client.query.return_value = result
    exe = ClickHouseMigrationExecutor(client)

    applied = _run(exe.fetch_applied())

    assert applied == {"001", "002"}
    client.query.assert_called_once()
    sql = client.query.call_args[0][0]
    assert "SELECT prefix FROM schema_migrations FINAL" in sql


def test_clickhouse_fetch_applied_empty_returns_empty_set() -> None:
    client = MagicMock()
    result = MagicMock()
    result.result_rows = []
    client.query.return_value = result
    exe = ClickHouseMigrationExecutor(client)

    applied = _run(exe.fetch_applied())

    assert applied == set()


def test_clickhouse_apply_one_runs_sql_then_books() -> None:
    """`apply_one()` issues TWO `command()` calls: the migration
    SQL, then the bookkeeping INSERT (with parameters)."""
    client = MagicMock()
    exe = ClickHouseMigrationExecutor(client)
    migration = Migration(
        prefix="003",
        name="add_klines",
        path=Path("003_add_klines.sql"),
        sql="CREATE TABLE klines (x Int32);",
    )

    _run(exe.apply_one(migration))

    assert client.command.call_count == 2
    # 1st call: migration SQL (positional arg)
    assert client.command.call_args_list[0][0][0] == "CREATE TABLE klines (x Int32);"
    # 2nd call: bookkeeping INSERT (with parameters kwarg)
    args, kwargs = client.command.call_args_list[1]
    assert "INSERT INTO schema_migrations" in args[0]
    assert kwargs["parameters"] == {"prefix": "003", "name": "add_klines"}


def test_clickhouse_apply_one_wraps_exception_in_migration_error() -> None:
    """A ClickHouse `command()` failure is wrapped in
    `MigrationError` (same contract as the Postgres
    executor). The error message includes the migration name."""
    client = MagicMock()
    client.command.side_effect = RuntimeError("table already exists")
    exe = ClickHouseMigrationExecutor(client)
    migration = Migration(
        prefix="004",
        name="collide",
        path=Path("004_collide.sql"),
        sql="CREATE TABLE t (x Int32);",
    )

    with pytest.raises(MigrationError) as exc_info:
        _run(exe.apply_one(migration))

    assert "collide" in str(exc_info.value)
    assert "table already exists" in str(exc_info.value)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _run(coro):
    """Run an async coroutine synchronously."""

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
