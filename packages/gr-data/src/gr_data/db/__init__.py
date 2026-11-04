"""数据库访问层。

PostgreSQL 实现在 ``postgres``，ClickHouse 实现在 ``clickhouse``，
DuckDB 临时计算工具在 ``duckdb``。本层导出常用 PostgreSQL 接口；
其余 PostgreSQL 模块从 ``gr_data.db.postgres.<module>`` 导入。
连接环境配置统一位于 ``gr_data.config``。
"""

from __future__ import annotations

from gr_data.db.postgres import (
    DictConnection,
    PgConfig,
    PgConnectionPool,
    PgPool,
    connect,
    pg_pool,
    upsert_rows,
)


__all__ = [
    "DictConnection",
    "PgConfig",
    "PgConnectionPool",
    "PgPool",
    "connect",
    "pg_pool",
    "upsert_rows",
]
