"""对外 code（如 STR_FUT_001 / SIG_20260415_001）↔ 内部 UUID 的解析。

本期无 Redis 缓存，直接打 PG。后续可加 LRU/Redis 二级缓存。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from gr_api.errors import NotFound


if TYPE_CHECKING:
    from psycopg import AsyncConnection


async def strategy_code_to_id(db: AsyncConnection, strategy_code: str) -> str:
    """根据 strategy_code 查 strategies.id (UUID 字符串)。"""
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT id FROM strategies WHERE strategy_code = %s",
            (strategy_code,),
        )
        row = await cur.fetchone()
    if row is None:
        raise NotFound(f"strategy not found: {strategy_code}")
    return str(row["id"])


async def signal_code_to_id(db: AsyncConnection, signal_code: str) -> str:
    """根据 signal_code 查 signals.id (UUID 字符串)。"""
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT id FROM signals WHERE signal_code = %s",
            (signal_code,),
        )
        row = await cur.fetchone()
    if row is None:
        raise NotFound(f"signal not found: {signal_code}")
    return str(row["id"])
