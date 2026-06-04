from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from getrich_data_import.db.postgres import qident, qualified
from getrich_data_import.transform.bars import market_table


@dataclass(frozen=True)
class ExportResult:
    path: Path
    rows: int


def export_bars_to_parquet(
    engine: Engine,
    *,
    output_path: Path,
    asset: str,
    freq: str,
    start_date: date | None = None,
    end_date: date | None = None,
    symbols: list[str] | None = None,
) -> ExportResult:
    table = market_table(asset, freq)
    where_sql, params = _bar_filters(start_date=start_date, end_date=end_date, symbols=symbols)
    sql = text(
        f"""
        SELECT i.asset,
               i.exchange,
               i.symbol,
               b.*
        FROM {qualified("market", table)} b
        JOIN meta.instruments i ON i.instrument_id = b.instrument_id
        {where_sql}
        ORDER BY i.symbol, b.dt
        """
    )

    with engine.connect() as conn:
        frame = pd.read_sql_query(sql, conn, params=params)

    _atomic_write_parquet(frame, output_path)
    return ExportResult(path=output_path, rows=int(len(frame)))


def _bar_filters(
    *,
    start_date: date | None,
    end_date: date | None,
    symbols: list[str] | None,
) -> tuple[str, dict[str, object]]:
    clauses: list[str] = []
    params: dict[str, object] = {}
    if start_date is not None:
        clauses.append(f"b.{qident('trading_day')} >= :start_date")
        params["start_date"] = start_date
    if end_date is not None:
        clauses.append(f"b.{qident('trading_day')} <= :end_date")
        params["end_date"] = end_date
    clean_symbols = [str(symbol).strip() for symbol in symbols or [] if str(symbol).strip()]
    if clean_symbols:
        clauses.append("i.symbol = ANY(:symbols)")
        params["symbols"] = clean_symbols
    if not clauses:
        return "", params
    return "WHERE " + " AND ".join(clauses), params


def _atomic_write_parquet(frame: pd.DataFrame, output_path: Path) -> None:
    output_path = output_path.expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(f".{output_path.name}.{os.getpid()}.tmp")
    try:
        frame.to_parquet(tmp_path, index=False, compression="zstd")
        os.replace(tmp_path, output_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
