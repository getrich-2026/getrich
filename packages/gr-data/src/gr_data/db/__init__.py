"""数据库层：连接池、批量 upsert。

两套 PostgreSQL 客户端，用途不同，不要混用：

- :mod:`gr_data.db.pool` —— ``AsyncConnectionPool`` 单例，给 FastAPI / 异步服务用。
- :mod:`gr_data.db.sync` —— 同步连接与连接池，给 ingest 批量入库和 CLI 用。
"""

from gr_data.db.copy import upsert_rows
from gr_data.db.pool import PgConnectionPool, pg_pool
from gr_data.db.sync import PgConfig, PgPool, connect


__all__ = [
    "PgConfig",
    "PgConnectionPool",
    "PgPool",
    "connect",
    "pg_pool",
    "upsert_rows",
]
