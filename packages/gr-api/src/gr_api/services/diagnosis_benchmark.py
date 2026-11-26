"""按快照中的已验证全收益基准身份取数。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from gr_data.common.benchmark import benchmark_version
from gr_data.db import DictConnection


@dataclass(frozen=True)
class BenchmarkReadResult:
    """结构化全收益基准读取结果，区分未选基准、版本校验失败与正常取数。"""

    status: Literal["ok", "benchmark_missing", "data_not_validated"]
    symbol: str | None
    name: str | None
    version: str | None
    returns: dict[date, float]
    reason: str | None = None


async def read_benchmark(
    db: DictConnection,
    instrument_id: int | None,
    version: str | None,
    window: tuple[date, date],
) -> BenchmarkReadResult:
    """校验整个全收益基准版本内容后返回身份与闭区间日简单收益。"""
    if instrument_id is None or not version:
        return BenchmarkReadResult(
            status="benchmark_missing",
            symbol=None,
            name=None,
            version=None,
            returns={},
            reason="未选择或缺少已准入的全收益基准。",
        )
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT i.symbol, i.name, b.dt, b.simple_return FROM market.index_total_return_1d b
            JOIN meta.instruments i ON i.instrument_id=b.instrument_id
            WHERE b.instrument_id=%s AND b.version=%s AND b.source='tushare'
            ORDER BY b.dt
            """,
            (instrument_id, version),
        )
        rows = await cur.fetchall()
    values = {row["dt"]: row["simple_return"] for row in rows}
    if not rows or benchmark_version(rows[0]["symbol"], values) != version:
        symbol = str(rows[0]["symbol"]) if rows else None
        raw_name = rows[0].get("name") if rows else None
        return BenchmarkReadResult(
            status="data_not_validated",
            symbol=symbol,
            name=(str(raw_name) if raw_name else symbol),
            version=version,
            returns={},
            reason="已绑定的全收益基准版本记录缺失或整版内容哈希校验未通过。",
        )
    symbol = str(rows[0]["symbol"])
    raw_name = rows[0].get("name")
    name = str(raw_name).strip() if raw_name else symbol
    if not name:
        name = symbol
    return BenchmarkReadResult(
        status="ok",
        symbol=symbol,
        name=name,
        version=version,
        returns={
            day: float(value) for day, value in values.items() if window[0] <= day <= window[1]
        },
    )


async def fetch_benchmark_returns(
    db: DictConnection,
    instrument_id: int | None,
    version: str | None,
    window: tuple[date, date],
) -> dict[date, float]:
    """校验整个版本内容后返回指定闭区间的日简单收益；缺失或指纹不匹配返回空映射。"""
    result = await read_benchmark(db, instrument_id, version, window)
    return result.returns if result.status == "ok" else {}
