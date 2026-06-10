"""ingest 共享辅助：标的 ID 解析。

bars 入库需要 instrument_id。解析顺序：
1. 优先用 meta.symbol_map（source + source_symbol → instrument_id）。
2. 回退用 meta.instruments（asset + exchange + symbol → instrument_id）。

返回 {source_symbol: instrument_id} 映射。
"""

from __future__ import annotations

import psycopg


def resolve_by_symbol_map(conn: psycopg.Connection, source: str) -> dict[str, int]:
    """返回某 source 下 {source_symbol: instrument_id}。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT source_symbol, instrument_id FROM meta.symbol_map WHERE source = %s",
            (source,),
        )
        return {r[0]: int(r[1]) for r in cur.fetchall()}


def resolve_by_instrument(conn: psycopg.Connection, asset: str) -> dict[str, int]:
    """返回某 asset 下 {symbol: instrument_id}（symbol 为 canonical 代码）。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, instrument_id FROM meta.instruments WHERE asset = %s",
            (asset,),
        )
        return {r[0]: int(r[1]) for r in cur.fetchall()}
