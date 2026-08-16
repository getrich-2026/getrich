"""GetRich 数据库定义与迁移。

本包是**全部数据库 DDL 的唯一真源**，覆盖七个 PostgreSQL schema
（``meta`` / ``market`` / ``realtime`` / ``staging`` / ``ops`` / ``app`` / ``backtest``）
与 ClickHouse 的因子时序表。

* 读 ``ddl/postgres/*.sql`` 应用 PostgreSQL DDL（文件名前缀 ``NNN_``，按数字序）。
* 读 ``ddl/clickhouse/*.sql`` 应用 ClickHouse DDL（同样的命名约定）。
* 在 ``ops.schema_migrations`` 里按 ``file_name -> checksum`` 记账。
* 只应用新增或内容变更过的文件；重复执行是 no-op。
* 前缀重复或不连续（如 003 跳到 005）时直接报错，不静默跳过。

所有 DDL 文件必须满足两条：**幂等**（``CREATE ... IF NOT EXISTS``）、
**schema 全限定**（``app.users`` 而非依赖 ``search_path`` 的 ``users``）。

命令行入口：``gr-db migrate|status --target pg|clickhouse|all``（见 :mod:`gr_db.cli`）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from gr_db.runner import (
    Migration,
    MigrationError,
    MigrationExecutor,
    MigrationPlan,
    apply_migrations,
    build_plan,
    discover_migrations,
    run_directory,
)


if TYPE_CHECKING:
    import psycopg


# DDL 随 wheel 安装（见 pyproject 的 package-data），路径基于包定位，
# 因此 pip 安装后也能建库，不依赖仓库布局。
DDL_ROOT = Path(__file__).resolve().parent / "ddl"
POSTGRES_DDL_DIR = DDL_ROOT / "postgres"
CLICKHOUSE_DDL_DIR = DDL_ROOT / "clickhouse"


def migrate_postgres(
    conn: psycopg.Connection,
    *,
    dry_run: bool = False,
    directory: Path | None = None,
) -> MigrationPlan:
    """在给定的**同步** psycopg 连接上应用全部 PostgreSQL DDL。

    给测试夹具和一次性脚本用的同步入口；命令行走 :mod:`gr_db.cli`。
    调用方负责连接的开启与关闭。
    """
    from gr_db.executors import PostgresMigrationExecutor

    executor = PostgresMigrationExecutor(conn)
    return asyncio.run(run_directory(directory or POSTGRES_DDL_DIR, executor, dry_run=dry_run))


__all__ = [
    "CLICKHOUSE_DDL_DIR",
    "DDL_ROOT",
    "POSTGRES_DDL_DIR",
    "Migration",
    "MigrationError",
    "MigrationExecutor",
    "MigrationPlan",
    "apply_migrations",
    "build_plan",
    "discover_migrations",
    "migrate_postgres",
    "run_directory",
]
