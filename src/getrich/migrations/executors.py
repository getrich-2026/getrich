"""PostgreSQL and ClickHouse executors for the migration runner.

The executor is the bridge between the pure-Python migration runner
(see :mod:`getrich.migrations.runner`) and a real database. The runner
calls three methods on the executor:

* :meth:`ensure_tracking_table` — create the ``schema_migrations``
  bookkeeping table if absent.
* :meth:`fetch_applied` — return the set of already-applied prefixes.
* :meth:`apply_one` — execute one migration's SQL and record the
  prefix in the tracking table. Each apply is transactional so a
  failure rolls back both the schema change and the bookkeeping row.

The PostgreSQL executor uses :mod:`psycopg` (sync, not the async pool
in ``getrich.libs.postgres.pool``) because migrations are a one-off
CLI operation, not a per-request hot path. Sync avoids the need for
``asyncio.run`` plumbing inside the CLI.

The ClickHouse executor uses :mod:`clickhouse_connect` (the same
client the application uses for analytics queries) so we keep a
single dependency on a known-good client.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .runner import Migration, MigrationError, MigrationExecutor


if TYPE_CHECKING:
    import psycopg
    from clickhouse_connect.driver.client import Client as ClickHouseClient


logger = logging.getLogger(__name__)


# Tracking table DDL — kept in sync between both backends.
_TRACKING_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    prefix        VARCHAR(16)   NOT NULL PRIMARY KEY,
    name          VARCHAR(255)  NOT NULL,
    applied_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW()
)
"""


_TRACKING_TABLE_DDL_CLICKHOUSE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    prefix        String,
    name          String,
    applied_at    DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY prefix
"""


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
        with conn.cursor() as cur:
            cur.execute("SET search_path TO frontend")
        logger.debug("set search_path = frontend on migration connection")

    async def ensure_tracking_table(self) -> None:
        # Sync psycopg calls are blocking; they're safe inside this
        # async method because migrations run from a one-off CLI and
        # not on a hot event loop.
        with self._conn.cursor() as cur:
            cur.execute(_TRACKING_TABLE_DDL)
        self._conn.commit()
        logger.debug("ensured schema_migrations table exists")

    async def fetch_applied(self) -> set[str]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT prefix FROM schema_migrations")
            rows = cur.fetchall()
        return {row[0] for row in rows}

    async def apply_one(self, migration: Migration) -> None:
        try:
            with self._conn.cursor() as cur:
                cur.execute(migration.sql)
            with self._conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO schema_migrations (prefix, name) VALUES (%s, %s)",
                    (migration.prefix, migration.name),
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

    async def fetch_applied(self) -> set[str]:
        rows = self._client.query("SELECT prefix FROM schema_migrations FINAL").result_rows
        return {row[0] for row in rows}

    async def apply_one(self, migration: Migration) -> None:
        try:
            self._client.command(migration.sql)
            self._client.command(
                "INSERT INTO schema_migrations (prefix, name) VALUES",
                parameters={"prefix": migration.prefix, "name": migration.name},
            )
        except Exception as exc:  # noqa: BLE001
            raise MigrationError(f"clickhouse migration {migration.name!r} failed: {exc}") from exc
