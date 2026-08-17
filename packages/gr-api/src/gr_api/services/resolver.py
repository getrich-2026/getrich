"""对外 code（如 STR_FUT_001 / SIG_20260415_001）↔ 内部 UUID 的解析。

本期无 Redis 缓存，直接打 PG。后续可加 LRU/Redis 二级缓存。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

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


async def resolve_strategy_ref(db: AsyncConnection, ref: str) -> dict[str, Any]:
    """按 UUID 或 ``strategy_code`` 解析策略，返回基础信息。

    选股模块的接口契约（``选股展示模块.openapi.json`` 的 ``StrategyId`` 参数）
    允许前端传 UUID 或 ``STR_STK_001`` 这种 code，两者都要认。

    Args:
        db: PostgreSQL 异步连接。
        ref: 策略 UUID 字符串或 ``strategy_code``。

    Returns:
        ``{id, strategy_code, name, strategy_kind}``。

    Raises:
        NotFound: 两种写法都没查到。
    """
    try:
        UUID(str(ref))
    except (ValueError, AttributeError, TypeError):
        where, param = "strategy_code = %s", str(ref)
    else:
        where, param = "id = %s::uuid", str(ref)

    async with db.cursor() as cur:
        await cur.execute(
            f"SELECT id, strategy_code, name, strategy_kind FROM strategies WHERE {where}",
            (param,),
        )
        row = await cur.fetchone()
    if row is None:
        raise NotFound(f"strategy not found: {ref}")
    return row


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
