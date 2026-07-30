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
from psycopg.conninfo import make_conninfo


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
        """构造 libpq 连接串。

        必须用 ``make_conninfo`` 而不是 f-string 拼接：keyword=value 格式里，
        含空格 / 单引号 / 反斜杠的值需要转义。手工拼接时密码含空格会直接
        ProgrammingError，含反斜杠更糟——会被**静默**解析成另一个值
        （``a\\b`` → ``a\b``），表现为莫名其妙的认证失败。
        """
        return make_conninfo(
            host=self.host,
            port=self.port,
            dbname=self.dbname,
            user=self.user,
            password=self.password,
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
