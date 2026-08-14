"""PostgreSQL 异步连接池（前端业务库 goldmine）。

使用方式：
    from getrich.libs.postgres import pg_pool

    await pg_pool.init()           # 应用启动时
    async with pg_pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1")
    await pg_pool.close()          # 应用关闭时
"""

from getrich.libs.postgres.pool import PgConnectionPool, pg_pool


__all__ = ["PgConnectionPool", "pg_pool"]
