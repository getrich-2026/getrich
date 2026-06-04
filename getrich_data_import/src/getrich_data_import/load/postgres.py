from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection

from getrich_data_import.db.postgres import qident, qualified, table_columns
from getrich_data_import.services.symbol_map import SymbolMapService


def upsert_dataframe(
    conn: Connection,
    df: pd.DataFrame,
    *,
    schema: str,
    table: str,
    primary_keys: Sequence[str],
    batch_rows: int = 50_000,
) -> int:
    if df.empty:
        return 0

    target_cols = table_columns(conn, schema, table)
    cols = [col for col in df.columns if col in target_cols]
    missing_keys = [key for key in primary_keys if key not in cols]
    if missing_keys:
        raise ValueError(f"{schema}.{table}: missing primary key columns: {missing_keys}")

    tmp_name = f"tmp_getrich_{uuid.uuid4().hex[:12]}"
    safe_chunk = min(batch_rows, max(1, 60_000 // max(1, len(cols))))
    df.loc[:, cols].to_sql(
        tmp_name,
        con=conn,
        schema="pg_temp",
        if_exists="replace",
        index=False,
        chunksize=safe_chunk,
        method="multi",
    )

    col_sql = ", ".join(qident(col) for col in cols)
    pk_sql = ", ".join(qident(col) for col in primary_keys)
    update_cols = [col for col in cols if col not in primary_keys]
    if update_cols:
        set_sql = ", ".join(f"{qident(col)} = EXCLUDED.{qident(col)}" for col in update_cols)
        if "updated_at" in target_cols and "updated_at" not in cols:
            set_sql += ", updated_at = now()"
        conflict_sql = f"DO UPDATE SET {set_sql}"
    else:
        conflict_sql = "DO NOTHING"

    result = conn.execute(
        text(
            f"""
            INSERT INTO {qualified(schema, table)} ({col_sql})
            SELECT {col_sql}
            FROM pg_temp.{qident(tmp_name)}
            ON CONFLICT ({pk_sql}) {conflict_sql}
            """
        )
    )
    return int(result.rowcount or 0)


def attach_instrument_ids(conn: Connection, df: pd.DataFrame, *, source: str) -> pd.DataFrame:
    if df.empty:
        return df
    symbols = sorted(set(df["source_symbol"].dropna().astype(str)))
    mapping = SymbolMapService(conn).resolve_many(source=source, source_symbols=symbols)
    out = df.copy()
    out["instrument_id"] = out["source_symbol"].map(
        lambda source_symbol: mapping[str(source_symbol)].instrument_id
    )
    return out


def insert_job_run(
    conn: Connection,
    *,
    job_name: str,
    asset: str | None = None,
    freq: str | None = None,
    trading_day: date | None = None,
) -> int:
    return int(
        conn.execute(
            text(
                """
                INSERT INTO ops.etl_job_run
                    (job_name, trading_day, asset, freq, status, started_at)
                VALUES (:job_name, :trading_day, :asset, :freq, 'running', now())
                RETURNING run_id
                """
            ),
            {
                "job_name": job_name,
                "trading_day": trading_day,
                "asset": asset,
                "freq": freq,
            },
        ).scalar_one()
    )


def finish_job_run(
    conn: Connection,
    *,
    run_id: int,
    status: str,
    rows_written: int,
    error: str | None = None,
) -> None:
    conn.execute(
        text(
            """
            UPDATE ops.etl_job_run
            SET status = :status,
                rows_written = :rows_written,
                finished_at = now(),
                error = :error
            WHERE run_id = :run_id
            """
        ),
        {
            "run_id": run_id,
            "status": status,
            "rows_written": rows_written,
            "error": error,
        },
    )
