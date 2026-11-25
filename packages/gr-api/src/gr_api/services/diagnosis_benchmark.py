"""按快照中的已验证全收益基准身份取数。"""

from __future__ import annotations

from datetime import date

from gr_data.common.benchmark import benchmark_version
from gr_data.db import DictConnection


async def fetch_benchmark_returns(
    db: DictConnection,
    instrument_id: int | None,
    version: str | None,
    window: tuple[date, date],
) -> dict[date, float]:
    """校验整个版本内容后返回指定闭区间的日简单收益；缺失或指纹不匹配返回空映射。"""
    if instrument_id is None or not version:
        return {}
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT i.symbol, b.dt, b.simple_return FROM market.index_total_return_1d b
            JOIN meta.instruments i ON i.instrument_id=b.instrument_id
            WHERE b.instrument_id=%s AND b.version=%s AND b.source='tushare'
            ORDER BY b.dt
            """,
            (instrument_id, version),
        )
        rows = await cur.fetchall()
    values = {row["dt"]: row["simple_return"] for row in rows}
    if not rows or benchmark_version(rows[0]["symbol"], values) != version:
        return {}
    return {day: value for day, value in values.items() if window[0] <= day <= window[1]}
