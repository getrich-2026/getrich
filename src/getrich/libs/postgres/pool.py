"""基于 psycopg3 AsyncConnectionPool 的 PostgreSQL 连接池单例。

设计目标对齐 ``libs/clickhouse/pool.py``：
- 单例使用，应用启动时 ``init()``，关闭时 ``close()``
- 通过 ``connection()`` 获取异步连接（async context manager）
- 连接级强制 timezone='Asia/Shanghai'，与项目 CLAUDE.md 时区规则一致
- row_factory=dict_row：所有查询结果默认按列名返回 dict
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


if TYPE_CHECKING:
    from psycopg import AsyncConnection


class PgConnectionPool:
    """PostgreSQL 异步连接池封装。"""

    def __init__(self) -> None:
        self._pool: AsyncConnectionPool | None = None

    async def init(self) -> None:
        """初始化连接池并预热连接。重复调用会被忽略。"""
        if self._pool is not None:
            return

        # 延迟导入 settings，避免在模块加载阶段触发配置校验
        from getrich.config import settings

        cfg = settings.postgres
        dsn = (
            f"postgresql://{cfg.user}:{cfg.password}@{cfg.host}:{cfg.port}/{cfg.database}"
            f"?application_name=getrich-web"
        )
        self._pool = AsyncConnectionPool(
            conninfo=dsn,
            min_size=cfg.min_size,
            max_size=cfg.max_size,
            kwargs={
                "row_factory": dict_row,
                "options": "-c timezone=Asia/Shanghai",
            },
            open=False,
        )
        await self._pool.open(wait=True)

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection]:
        """获取一个异步连接（用完自动归还）。"""
        if self._pool is None:
            raise RuntimeError("PgConnectionPool.init() has not been called")
        async with self._pool.connection() as conn:
            yield conn

    async def close(self) -> None:
        """关闭连接池。"""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def is_ready(self) -> bool:
        return self._pool is not None


# 单例
pg_pool = PgConnectionPool()
