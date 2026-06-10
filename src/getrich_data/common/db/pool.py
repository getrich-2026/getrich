"""PostgreSQL 连接（psycopg3）。

提供同步连接工厂与可选连接池。入库走原生 SQL + executemany/COPY，不用重 ORM
（见 CLAUDE.md 铁律）。同步实现足够覆盖批量入库；实时层另用独立写入器。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import psycopg


@dataclass
class PgConfig:
    host: str = "localhost"
    port: int = 5432
    dbname: str = "getrich"
    user: str = "postgres"
    password: str = ""
    statement_timeout_ms: int = 60000

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PgConfig:
        return cls(
            host=d.get("host", "localhost"),
            port=int(d.get("port", 5432)),
            dbname=d.get("dbname", "getrich"),
            user=d.get("user", "postgres"),
            # config.resolve_secret_fields 会把 password_env 解析为 password
            password=d.get("password", d.get("password_env", "")) or "",
            statement_timeout_ms=int(d.get("statement_timeout_ms", 60000)),
        )

    def conninfo(self) -> str:
        return (
            f"host={self.host} port={self.port} dbname={self.dbname} "
            f"user={self.user} password={self.password}"
        )


@contextmanager
def connect(cfg: PgConfig) -> Iterator[psycopg.Connection]:
    """打开一个连接，设置 statement_timeout，结束自动关闭。"""
    conn = psycopg.connect(cfg.conninfo(), autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = {int(cfg.statement_timeout_ms)}")
        conn.commit()
        yield conn
    finally:
        conn.close()


class PgPool:
    """轻量连接池包装（psycopg_pool）。批量入库可直接用 connect()；池供长驻进程用。"""

    def __init__(self, cfg: PgConfig, min_size: int = 1, max_size: int = 8):
        from psycopg_pool import ConnectionPool

        self._pool = ConnectionPool(
            cfg.conninfo(), min_size=min_size, max_size=max_size, open=True
        )

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        with self._pool.connection() as conn:
            yield conn

    def close(self) -> None:
        self._pool.close()
