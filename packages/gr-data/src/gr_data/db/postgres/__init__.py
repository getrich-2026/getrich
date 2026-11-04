"""PostgreSQL：同步／异步连接与批量写入。

两套 PostgreSQL 客户端，用途不同，不要混用：

- :mod:`gr_data.db.postgres.pool` —— ``AsyncConnectionPool`` 单例，给 FastAPI / 异步服务用。
- :mod:`gr_data.db.postgres.sync` —— 同步连接与连接池，给 ingest 批量入库和 CLI 用。
"""

from __future__ import annotations

from gr_data.db.postgres.copy import upsert_rows
from gr_data.db.postgres.pool import DictConnection, PgConnectionPool, pg_pool
from gr_data.db.postgres.sync import PgConfig, PgPool, connect


__all__ = [
    "DictConnection",
    "PgConfig",
    "PgConnectionPool",
    "PgPool",
    "connect",
    "pg_pool",
    "upsert_rows",
]
