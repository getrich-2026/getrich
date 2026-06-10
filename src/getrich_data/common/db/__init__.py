"""数据库层：连接池、批量 upsert。"""

from getrich_data.common.db.copy import upsert_rows
from getrich_data.common.db.pool import PgConfig, PgPool, connect

__all__ = ["PgConfig", "PgPool", "connect", "upsert_rows"]
