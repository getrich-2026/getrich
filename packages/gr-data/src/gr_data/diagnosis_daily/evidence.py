"""诊断日更证据：范围指纹与原子落盘，不含连接配置。"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timezone
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


def archive_failed_attempt(artifact: Path, day: date) -> dict[str, str] | None:
    """原子移走没有prepared的失败尝试；保留原件、计划及状态的原始内容。"""
    if (artifact / "prepared.json").exists():
        raise ValueError("Prepared artifacts cannot be archived as failed attempts")
    if not artifact.exists():
        return None
    if artifact.is_symlink() or not artifact.is_dir():
        raise ValueError("Failed attempt must be a regular artifact directory")
    if not any(artifact.iterdir()):
        return None
    archive_root = artifact.parent / "_failed"
    if archive_root.is_symlink():
        raise ValueError("Failed attempt archive must not be a symbolic link")
    archive_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc)
    archived = archive_root / f"{day}-{stamp:%Y%m%dT%H%M%S%fZ}-{uuid4().hex}"
    artifact.rename(archived)
    return {
        "day": str(day),
        "path": str(archived.resolve()),
        "source": str(artifact.absolute()),
        "archived_at": stamp.isoformat(),
    }


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
