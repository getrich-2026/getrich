"""DDL / 迁移执行器。

按文件名顺序执行 ``db/ddl/*.sql`` 与 ``db/migrations/*.sql``，并在
``ops.schema_migrations`` 记录文件名与 checksum，已应用且内容未变的文件跳过。

- ``migrate(conn)``：应用所有未应用（或已变更）的 SQL 文件。
- ``status(conn)``：返回每个文件的应用状态。

注意：``ops.schema_migrations`` 由 50_ops.sql 创建，故首个 ddl 文件总会执行
（用 IF NOT EXISTS 幂等），记录表就绪后再记账。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import psycopg

from gr_data.logging import get_logger


log = get_logger(__name__)

# 仓库根下的 db 目录
_DB_DIR = Path(__file__).resolve().parents[3] / "db"
DDL_DIR = _DB_DIR / "ddl"
MIGRATIONS_DIR = _DB_DIR / "migrations"


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ordered_sql_files() -> list[Path]:
    files: list[Path] = []
    if DDL_DIR.is_dir():
        files += sorted(DDL_DIR.glob("*.sql"))
    if MIGRATIONS_DIR.is_dir():
        files += sorted(MIGRATIONS_DIR.glob("*.sql"))
    return files


def _ensure_migrations_table(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS ops")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ops.schema_migrations (
                file_name  TEXT PRIMARY KEY,
                checksum   TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    conn.commit()


def _applied_checksums(conn: psycopg.Connection) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT file_name, checksum FROM ops.schema_migrations")
        return {r[0]: r[1] for r in cur.fetchall()}


@dataclass
class MigrationResult:
    file_name: str
    action: str  # 'applied' | 'skipped' | 'reapplied'


def migrate(conn: psycopg.Connection) -> list[MigrationResult]:
    """应用所有未应用/已变更的 SQL 文件。每个文件单独事务提交。"""
    _ensure_migrations_table(conn)
    applied = _applied_checksums(conn)
    results: list[MigrationResult] = []

    for path in _ordered_sql_files():
        name = path.name
        sql = path.read_text(encoding="utf-8")
        checksum = _checksum(sql)

        if applied.get(name) == checksum:
            results.append(MigrationResult(name, "skipped"))
            continue

        action = "reapplied" if name in applied else "applied"
        log.info("应用 SQL: %s (%s)", name, action)
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                """
                INSERT INTO ops.schema_migrations (file_name, checksum, applied_at)
                VALUES (%s, %s, now())
                ON CONFLICT (file_name) DO UPDATE
                  SET checksum = EXCLUDED.checksum, applied_at = now()
                """,
                (name, checksum),
            )
        conn.commit()
        results.append(MigrationResult(name, action))

    return results


def status(conn: psycopg.Connection) -> list[MigrationResult]:
    """返回每个文件的状态，不做任何变更。"""
    _ensure_migrations_table(conn)
    applied = _applied_checksums(conn)
    out: list[MigrationResult] = []
    for path in _ordered_sql_files():
        name = path.name
        checksum = _checksum(path.read_text(encoding="utf-8"))
        if name not in applied:
            out.append(MigrationResult(name, "pending"))
        elif applied[name] != checksum:
            out.append(MigrationResult(name, "changed"))
        else:
            out.append(MigrationResult(name, "applied"))
    return out
