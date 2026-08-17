"""PostgreSQL and ClickHouse executors for the migration runner.

The executor is the bridge between the pure-Python migration runner
(see :mod:`gr_db.runner`) and a real database. The runner
calls three methods on the executor:

* :meth:`ensure_tracking_table` — create the ``schema_migrations``
  bookkeeping table if absent.
* :meth:`fetch_applied` — return ``{file_name: checksum}`` of已应用文件。
* :meth:`apply_one` — execute one migration's SQL and record the
  name + checksum in the tracking table. Each apply is transactional so a
  failure rolls back both the schema change and the bookkeeping row.

The PostgreSQL executor uses :mod:`psycopg` (sync, not the async pool
in ``gr_data.db.pool``) because migrations are a one-off
CLI operation, not a per-request hot path. Sync avoids the need for
``asyncio.run`` plumbing inside the CLI.

The ClickHouse executor uses :mod:`clickhouse_connect` (the same
client the application uses for analytics queries) so we keep a
single dependency on a known-good client.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from .runner import Migration, MigrationError, MigrationExecutor


if TYPE_CHECKING:
    import psycopg
    from clickhouse_connect.driver.client import Client as ClickHouseClient


logger = logging.getLogger(__name__)


# 记账表放 ops schema —— 它是运维元数据，不属于任何业务域。
# 建表语句自带 CREATE SCHEMA，因为 ensure_tracking_table() 必须在
# 001_extensions.sql 跑之前就能成功（先有记账表才能记账）。
_TRACKING_TABLE_DDL = """
CREATE SCHEMA IF NOT EXISTS ops;
CREATE TABLE IF NOT EXISTS ops.schema_migrations (
    file_name     VARCHAR(255)  NOT NULL PRIMARY KEY,
    checksum      CHAR(64)      NOT NULL,
    applied_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW()
)
"""


_TRACKING_TABLE_DDL_CLICKHOUSE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    file_name     String,
    checksum      String,
    applied_at    DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(applied_at)
ORDER BY file_name
"""


def split_statements(sql: str) -> list[str]:
    """把一个 SQL 文件切成多条语句（供不支持多语句的客户端使用）。

    只做朴素切分：去掉行注释后按 ``;`` 分割。ClickHouse 的
    ``client.command()`` 一次只吃一条语句，而 DDL 文件里可能有多张表。
    PostgreSQL 侧不需要切分（psycopg 支持多语句），因此不要在 PG 执行器里用它 ——
    切分会破坏 ``DO $$ ... $$`` 块里的分号。
    """
    without_comments = re.sub(r"--[^\n]*", "", sql)
    return [s.strip() for s in without_comments.split(";") if s.strip()]


# ---------------------------------------------------------------- PostgreSQL


class PostgresMigrationExecutor(MigrationExecutor):
    """Apply PostgreSQL migrations using a sync :mod:`psycopg` connection.

    Parameters
    ----------
    conn : psycopg.Connection
        An open psycopg (v3) sync connection. The caller is responsible
        for opening / closing it; the executor does not commit anything
        outside of the per-migration transaction it manages internally.
    """

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn
        # 迁移连接不设 search_path：所有 DDL 文件都写全限定名
        # （``app.``／``backtest.``／``market.`` …）。靠 search_path 隐式定位
        # schema 正是旧 ``frontend`` 方案的坑 —— 换个连接就建到 public 去了。
        with conn.cursor() as cur:
            cur.execute("SET search_path TO pg_catalog, public")
        logger.debug("migration connection uses fully-qualified schema names")

    async def ensure_tracking_table(self) -> None:
        # Sync psycopg calls are blocking; they're safe inside this
        # async method because migrations run from a one-off CLI and
        # not on a hot event loop.
        with self._conn.cursor() as cur:
            cur.execute(_TRACKING_TABLE_DDL)
        self._conn.commit()
        logger.debug("ensured ops.schema_migrations table exists")

    async def fetch_applied(self) -> dict[str, str]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT file_name, checksum FROM ops.schema_migrations")
            rows = cur.fetchall()
        return {row[0]: row[1] for row in rows}

    async def apply_one(self, migration: Migration) -> None:
        try:
            with self._conn.cursor() as cur:
                cur.execute(migration.sql)
            with self._conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ops.schema_migrations (file_name, checksum)
                    VALUES (%s, %s)
                    ON CONFLICT (file_name)
                    DO UPDATE SET checksum = EXCLUDED.checksum, applied_at = NOW()
                    """,
                    (migration.name, migration.checksum),
                )
            self._conn.commit()
        except Exception as exc:  # noqa: BLE001
            # Roll back the partial transaction so the connection is
            # usable for subsequent migrations.
            self._conn.rollback()
            raise MigrationError(f"postgres migration {migration.name!r} failed: {exc}") from exc


# ---------------------------------------------------------------- ClickHouse


class ClickHouseMigrationExecutor(MigrationExecutor):
    """Apply ClickHouse migrations using :mod:`clickhouse_connect`.

    ClickHouse does not support classical transactions across
    statements, so we use the application's existing client (which
    provides per-statement semantics) and accept that a partial failure
    may leave a migration partially applied. Migration files should
    therefore be written to be idempotent (``CREATE TABLE IF NOT
    EXISTS``) or to be small enough that a re-run is feasible.
    """

    def __init__(self, client: ClickHouseClient) -> None:
        self._client = client

    async def ensure_tracking_table(self) -> None:
        self._client.command(_TRACKING_TABLE_DDL_CLICKHOUSE)
        logger.debug("ensured schema_migrations table exists (clickhouse)")

    async def fetch_applied(self) -> dict[str, str]:
        rows = self._client.query(
            "SELECT file_name, checksum FROM schema_migrations FINAL"
        ).result_rows
        return {row[0]: row[1] for row in rows}

    async def apply_one(self, migration: Migration) -> None:
        try:
            # command() 一次只接受一条语句，DDL 文件可能有多张表，需先切分。
            for statement in split_statements(migration.sql):
                self._client.command(statement)
            # 必须走 insert()，不能用 command() 拼 "INSERT ... VALUES" —— 那条
            # SQL 里没有占位符，parameters 无处可绑，ClickHouse 会当成插入 0 行
            # 静默成功，记账表永远是空的，每次 migrate 都把全部迁移重放一遍。
            self._client.insert(
                "schema_migrations",
                [[migration.name, migration.checksum]],
                column_names=["file_name", "checksum"],
            )
        except Exception as exc:  # noqa: BLE001
            raise MigrationError(f"clickhouse migration {migration.name!r} failed: {exc}") from exc
