"""Tests for ``gr_db.executors``.

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
import hashlib
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from gr_db.executors import (
    ClickHouseMigrationExecutor,
    PostgresMigrationExecutor,
)
from gr_db.runner import Migration, MigrationError


pytestmark = pytest.mark.anyio


def _sum(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


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


def test_postgres_constructor_does_not_rely_on_search_path() -> None:
    """迁移连接不钉业务 schema —— 所有 DDL 都写全限定名。

    旧实现把 ``search_path`` 钉成 ``frontend``，DDL 里靠它隐式定位 schema；
    换个连接或改了 search_path 就会把表建到 public 去。现在 DDL 一律写
    ``app.``／``backtest.``／``market.``，这里只把 search_path 收窄到系统默认。
    """
    conn = _FakeConn()
    PostgresMigrationExecutor(conn)

    assert len(conn.cursors) == 1
    cur = conn.cursors[0]
    assert cur.executed[0][0] == "SET search_path TO pg_catalog, public"
    assert "frontend" not in cur.executed[0][0]


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
    assert "CREATE TABLE IF NOT EXISTS ops.schema_migrations" in ddl
    assert "CREATE SCHEMA IF NOT EXISTS ops" in ddl
    assert "PRIMARY KEY" in ddl
    assert conn.commits == 1


def test_postgres_fetch_applied_returns_name_to_checksum() -> None:
    """`fetch_applied()` 读 ``(file_name, checksum)``，返回账本字典。"""
    conn = _FakeConn(fetchall_rows=[("001_a.sql", "aa"), ("002_b.sql", "bb")])
    exe = PostgresMigrationExecutor(conn)

    applied = _run(exe.fetch_applied())

    assert applied == {"001_a.sql": "aa", "002_b.sql": "bb"}
    sql = conn.cursors[1].executed[0][0]
    assert sql == "SELECT file_name, checksum FROM ops.schema_migrations"


def test_postgres_fetch_applied_empty_returns_empty_set() -> None:
    """Fresh DB: no rows in the tracking table → empty set
    (the runner then plans to apply EVERY discovered
    migration)."""
    conn = _FakeConn(fetchall_rows=[])
    exe = PostgresMigrationExecutor(conn)

    applied = _run(exe.fetch_applied())

    assert applied == {}


def test_postgres_apply_one_runs_sql_then_books() -> None:
    """`apply_one()` runs the migration SQL, then INSERTs
    a bookkeeping row with the migration's prefix and name.
    Both happen inside one transaction (single commit)."""
    conn = _FakeConn()
    exe = PostgresMigrationExecutor(conn)
    migration = Migration(
        prefix="005",
        name="005_add_users.sql",
        path=Path("005_add_users.sql"),
        sql="CREATE TABLE users (id INT);",
        checksum=_sum("CREATE TABLE users (id INT);"),
    )

    _run(exe.apply_one(migration))

    # 3 cursors: constructor (SET), migration SQL, bookkeeping.
    assert len(conn.cursors) == 3
    sql_cur, book_cur = conn.cursors[1], conn.cursors[2]
    assert sql_cur.executed[0][0] == "CREATE TABLE users (id INT);"
    insert_sql, insert_params = book_cur.executed[0]
    assert "INSERT INTO ops.schema_migrations" in insert_sql
    assert "ON CONFLICT (file_name)" in insert_sql
    assert insert_params == ("005_add_users.sql", _sum("CREATE TABLE users (id INT);"))
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
        name="006_broken.sql",
        path=Path("006_broken.sql"),
        sql="BAD SQL",
        checksum=_sum("BAD SQL"),
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

    assert "006_broken.sql" in str(exc_info.value)
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
        name="007_dup_prefix.sql",
        path=Path("007_dup_prefix.sql"),
        sql="CREATE TABLE t (x INT);",
        checksum=_sum("CREATE TABLE t (x INT);"),
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


def test_clickhouse_ensure_tracking_table_uses_replacing_merge_tree() -> None:
    """CH 记账表用 ``ReplacingMergeTree(applied_at)``。

    改用 checksum 记账后，同一个 ``file_name`` 会因内容变更被重复写入；
    普通 MergeTree 会留下多行历史，``FINAL`` 去重时无法确定保留哪一行。
    ``ReplacingMergeTree(applied_at)`` 按 applied_at 取最新，语义正确。
    """
    client = MagicMock()
    exe = ClickHouseMigrationExecutor(client)

    _run(exe.ensure_tracking_table())

    # `command` is called with the DDL.
    client.command.assert_called_once()
    ddl = client.command.call_args[0][0]
    assert "CREATE TABLE IF NOT EXISTS schema_migrations" in ddl
    assert "ENGINE = ReplacingMergeTree(applied_at)" in ddl
    assert "ORDER BY file_name" in ddl


def test_clickhouse_fetch_applied_uses_final_keyword() -> None:
    """ClickHouse doesn't enforce uniqueness on MergeTree, so
    the executor must use `SELECT ... FINAL` to dedup any
    duplicates that may have been inserted by a prior run."""
    client = MagicMock()
    result = MagicMock()
    result.result_rows = [("001_a.sql", "aa"), ("002_b.sql", "bb")]
    client.query.return_value = result
    exe = ClickHouseMigrationExecutor(client)

    applied = _run(exe.fetch_applied())

    assert applied == {"001_a.sql": "aa", "002_b.sql": "bb"}
    client.query.assert_called_once()
    sql = client.query.call_args[0][0]
    assert "SELECT file_name, checksum FROM schema_migrations FINAL" in sql


def test_clickhouse_fetch_applied_empty_returns_empty_set() -> None:
    client = MagicMock()
    result = MagicMock()
    result.result_rows = []
    client.query.return_value = result
    exe = ClickHouseMigrationExecutor(client)

    applied = _run(exe.fetch_applied())

    assert applied == {}


def test_clickhouse_apply_one_books_via_insert_not_command() -> None:
    """记账必须走 ``client.insert()``，不能用 ``command()`` 拼 INSERT 语句。

    这条曾经断言的是 ``command("INSERT INTO schema_migrations ... VALUES",
    parameters={...})``。那条 SQL 里没有占位符，``parameters`` 无处可绑，
    ClickHouse 把它当成插入 0 行并静默成功 —— 用 ``MagicMock`` 测当然过，
    打真库时记账表恒为空，每次 ``gr-db migrate --target ch`` 都会把全部迁移
    重放一遍。所以这里钉的是「调了 insert 且带上了两列的值」，
    而不是某条 SQL 的字面量。
    """
    client = MagicMock()
    exe = ClickHouseMigrationExecutor(client)
    checksum = _sum("CREATE TABLE klines (x Int32);")
    migration = Migration(
        prefix="003",
        name="003_add_klines.sql",
        path=Path("003_add_klines.sql"),
        sql="CREATE TABLE klines (x Int32);",
        checksum=checksum,
    )

    _run(exe.apply_one(migration))

    # 迁移 SQL 走 command()，split_statements 去掉了结尾分号
    assert client.command.call_count == 1
    assert client.command.call_args_list[0][0][0] == "CREATE TABLE klines (x Int32)"

    client.insert.assert_called_once()
    args, kwargs = client.insert.call_args
    assert args[0] == "schema_migrations"
    assert args[1] == [["003_add_klines.sql", checksum]]
    assert kwargs["column_names"] == ["file_name", "checksum"]


def test_clickhouse_apply_one_splits_multi_statement_file() -> None:
    """CH 的 ``command()`` 一次只吃一条语句，多表 DDL 必须先切分。

    不切分的话，一个文件里的第二张表会被静默忽略 —— 建库时看不出错，
    直到运行期查询报 "table doesn't exist"。
    """
    client = MagicMock()
    exe = ClickHouseMigrationExecutor(client)
    sql = "CREATE TABLE a (x Int32);\nCREATE TABLE b (y Int32);\n"
    migration = Migration(
        prefix="009",
        name="009_two_tables.sql",
        path=Path("009_two_tables.sql"),
        sql=sql,
        checksum=_sum(sql),
    )

    _run(exe.apply_one(migration))

    # 2 条 DDL 走 command()，记账走 insert()
    assert client.command.call_count == 2
    assert client.command.call_args_list[0][0][0] == "CREATE TABLE a (x Int32)"
    assert client.command.call_args_list[1][0][0] == "CREATE TABLE b (y Int32)"
    client.insert.assert_called_once()


def test_clickhouse_apply_one_wraps_exception_in_migration_error() -> None:
    """A ClickHouse `command()` failure is wrapped in
    `MigrationError` (same contract as the Postgres
    executor). The error message includes the migration name."""
    client = MagicMock()
    client.command.side_effect = RuntimeError("table already exists")
    exe = ClickHouseMigrationExecutor(client)
    migration = Migration(
        prefix="004",
        name="004_collide.sql",
        path=Path("004_collide.sql"),
        sql="CREATE TABLE t (x Int32);",
        checksum=_sum("CREATE TABLE t (x Int32);"),
    )

    with pytest.raises(MigrationError) as exc_info:
        _run(exe.apply_one(migration))

    assert "004_collide.sql" in str(exc_info.value)
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
