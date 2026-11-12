"""基于 psycopg3 AsyncConnectionPool 的 PostgreSQL 连接池单例。

连接池约定：
- 单例使用，应用启动时 ``init()``，关闭时 ``close()``
- 通过 ``connection()`` 获取异步连接（async context manager）
- 连接级强制 timezone='Asia/Shanghai'，与项目 AGENTS.md 时区规则一致
- row_factory=dict_row：所有查询结果默认按列名返回 dict
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TypeAlias

from psycopg import AsyncConnection
from psycopg.conninfo import make_conninfo
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from gr_data.config import PostgresConfig


# 连接池里的连接都用 dict_row，查询结果按列名返回 dict。
# 业务代码标注连接时用这个别名，不要写裸 ``AsyncConnection``：
# 裸写会被类型检查器当成默认的元组行，``row["id"]`` 全部报错。
DictConnection: TypeAlias = AsyncConnection[DictRow]


class PgConnectionPool:
    """PostgreSQL 异步连接池封装。"""

    def __init__(self) -> None:
        self._pool: AsyncConnectionPool[DictConnection] | None = None
        self._lifecycle_lock = asyncio.Lock()

    async def init(self, cfg: PostgresConfig) -> None:
        """初始化连接池并预热连接。重复调用会被忽略。"""
        async with self._lifecycle_lock:
            if self._pool is not None:
                return
            dsn = make_conninfo(
                host=cfg.host,
                port=cfg.port,
                user=cfg.user,
                password=cfg.password,
                dbname=cfg.database,
                application_name="getrich-web",
            )
            pool = AsyncConnectionPool(
                conninfo=dsn,
                connection_class=DictConnection,
                min_size=cfg.min_size,
                max_size=cfg.max_size,
                kwargs={
                    "row_factory": dict_row,
                    "options": "-c timezone=Asia/Shanghai -c search_path=app,market,meta,public",
                },
                open=False,
            )
            try:
                await pool.open(wait=True)
            except BaseException:
                await pool.close()
                raise
            self._pool = pool

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[DictConnection]:
        """获取一个异步连接（用完自动归还）。"""
        if self._pool is None:
            raise RuntimeError("PgConnectionPool.init() has not been called")
        async with self._pool.connection() as conn:
            yield conn

    async def close(self) -> None:
        """关闭连接池。"""
        async with self._lifecycle_lock:
            if self._pool is not None:
                await self._pool.close()
                self._pool = None

    @property
    def is_ready(self) -> bool:
        return self._pool is not None


# 单例
pg_pool = PgConnectionPool()
