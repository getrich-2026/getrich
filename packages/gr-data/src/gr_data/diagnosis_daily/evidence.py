"""诊断日更证据：范围指纹与原子落盘，不含连接配置。"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from pathlib import Path
from typing import Any, LiteralString
from uuid import uuid4

import polars as pl
import psycopg
from psycopg import sql


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, default=str, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid4().hex)
    try:
        temporary.write_text(json.dumps(value, default=str, ensure_ascii=False, indent=2))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_frame(path: Path, frame: pl.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid4().hex)
    try:
        frame.write_parquet(temporary, compression="zstd")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def scope_queries(ids: list[int], start: date, day: date) -> dict[str, tuple[LiteralString, tuple]]:
    return {
        "meta.instruments": (
            "SELECT * FROM meta.instruments WHERE instrument_id=ANY(%s) ORDER BY instrument_id",
            (ids,),
        ),
        "meta.symbol_map": (
            (
                "SELECT * FROM meta.symbol_map WHERE instrument_id=ANY(%s) ORDER BY "
                "source,source_symbol"
            ),
            (ids,),
        ),
        "meta.trading_calendar": (
            (
                "SELECT * FROM meta.trading_calendar WHERE exchange IN "
                "('XSHG','XSHE') AND trading_day BETWEEN %s AND %s ORDER BY "
                "exchange,trading_day"
            ),
            (start, day),
        ),
        "market.stock_bar_1d": (
            (
                "SELECT * FROM market.stock_bar_1d WHERE instrument_id=ANY(%s) AND dt"
                " BETWEEN %s AND %s ORDER BY instrument_id,dt"
            ),
            (ids, start, day),
        ),
        "market.stock_suspend_event": (
            (
                "SELECT * FROM market.stock_suspend_event WHERE instrument_id=ANY(%s)"
                " AND trading_day BETWEEN %s AND %s ORDER BY "
                "instrument_id,trading_day,suspend_type,source"
            ),
            (ids, start, day),
        ),
        "market.stock_suspend_coverage": (
            (
                "SELECT * FROM market.stock_suspend_coverage WHERE source='tushare' "
                "AND trading_day BETWEEN %s AND %s ORDER BY trading_day"
            ),
            (start, day),
        ),
        "fundamental.valuation_1d": (
            (
                "SELECT DISTINCT ON (instrument_id) * FROM fundamental.valuation_1d "
                "WHERE instrument_id=ANY(%s) AND trading_day<=%s ORDER BY "
                "instrument_id,trading_day DESC"
            ),
            (ids, day),
        ),
        "fundamental.indicator_q": (
            (
                "SELECT * FROM fundamental.indicator_q WHERE instrument_id=ANY(%s) "
                "AND ann_date<=%s ORDER BY instrument_id,end_date,ann_date"
            ),
            (ids, day),
        ),
        "classify.instrument_category": (
            (
                "SELECT * FROM classify.instrument_category WHERE "
                "instrument_id=ANY(%s) ORDER BY instrument_id,in_date"
            ),
            (ids,),
        ),
        "classify.instrument_industry": (
            (
                "SELECT * FROM classify.instrument_industry WHERE "
                "instrument_id=ANY(%s) ORDER BY "
                "instrument_id,scheme_code,level,in_date"
            ),
            (ids,),
        ),
        "classify.industry_node": (
            "SELECT * FROM classify.industry_node ORDER BY scheme_code,level,industry_code",
            (),
        ),
        "classify.scheme": ("SELECT * FROM classify.scheme ORDER BY scheme_code", ()),
    }


def fingerprints(conn: psycopg.Connection, ids: list[int], start: date, day: date) -> dict:
    """逐块哈希，不将整年行情载入内存；时间戳也属于 CAS 基线。"""
    result = {}
    for table, (query, args) in scope_queries(ids, start, day).items():
        h = hashlib.sha256()
        rows = 0
        with conn.cursor().copy(
            sql.SQL("COPY (SELECT to_jsonb(t)::text FROM ({}) t) TO STDOUT").format(sql.SQL(query)),
            args or None,
        ) as stream:
            for chunk in stream:
                h.update(chunk)
                rows += bytes(chunk).count(b"\n")
        result[table] = {"sha256": h.hexdigest(), "rows": rows}
    return result
