from __future__ import annotations

import uuid
from collections.abc import Sequence
from collections.abc import Mapping
from datetime import date
import json
from typing import Any

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
    target_types = table_column_types(conn, schema, table)
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
    select_sql = ", ".join(_select_with_cast(col, target_types.get(col)) for col in cols)
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
            SELECT {select_sql}
            FROM pg_temp.{qident(tmp_name)}
            ON CONFLICT ({pk_sql}) {conflict_sql}
            """
        )
    )
    rows = int(result.rowcount or 0)
    conn.execute(text(f"DROP TABLE IF EXISTS pg_temp.{qident(tmp_name)}"))
    return rows


def table_column_types(conn: Connection, schema: str, table: str) -> dict[str, str]:
    rows = conn.execute(
        text(
            """
            SELECT a.attname AS column_name,
                   pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type
            FROM pg_catalog.pg_attribute a
            JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = :schema
              AND c.relname = :table
              AND a.attnum > 0
              AND NOT a.attisdropped
            ORDER BY a.attnum
            """
        ),
        {"schema": schema, "table": table},
    ).mappings()
    return {str(row["column_name"]): str(row["data_type"]) for row in rows}


def _select_with_cast(column: str, data_type: str | None) -> str:
    ident = qident(column)
    if not data_type:
        return ident
    return f"{ident}::{data_type}"


def attach_instrument_ids(conn: Connection, df: pd.DataFrame, *, source: str) -> pd.DataFrame:
    if df.empty:
        return df
    symbols = sorted(set(df["source_symbol"].dropna().astype(str)))
    mapping = SymbolMapService(conn).resolve_many(source=source, source_symbols=symbols)
    out = df.copy()
    out["instrument_id"] = out["source_symbol"].map(
        lambda source_symbol: mapping[str(source_symbol)].instrument_id
    )
    out["asset"] = out["source_symbol"].map(lambda source_symbol: mapping[str(source_symbol)].asset)
    out["exchange"] = out["source_symbol"].map(lambda source_symbol: mapping[str(source_symbol)].exchange)
    out["symbol"] = out["source_symbol"].map(lambda source_symbol: mapping[str(source_symbol)].symbol)
    return out


def insert_job_run(
    conn: Connection,
    *,
    job_name: str,
    provider: str | None = None,
    dataset_name: str | None = None,
    asset: str | None = None,
    freq: str | None = None,
    trading_day: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    request: Mapping[str, Any] | None = None,
) -> int:
    """Insert an ETL run audit row and return its run id.

    Args:
        conn: Active SQLAlchemy connection.
        job_name: Stable job name.
        provider: Data provider name.
        dataset_name: Dataset being fetched or loaded.
        asset: Optional asset class.
        freq: Optional frequency.
        trading_day: Single trading day for legacy jobs.
        start_date: Inclusive request or manifest start date.
        end_date: Inclusive request or manifest end date.
        request: JSON-serializable request payload.

    Time Complexity:
        O(1).
    Space Complexity:
        O(r), where r is the serialized request payload size.
    """

    return int(
        conn.execute(
            text(
                """
                INSERT INTO ops.etl_job_run
                    (
                        job_name,
                        provider,
                        dataset_name,
                        trading_day,
                        start_date,
                        end_date,
                        asset,
                        freq,
                        status,
                        request,
                        started_at
                    )
                VALUES (
                    :job_name,
                    :provider,
                    :dataset_name,
                    :trading_day,
                    :start_date,
                    :end_date,
                    :asset,
                    :freq,
                    'running',
                    CAST(:request AS jsonb),
                    now()
                )
                RETURNING run_id
                """
            ),
            {
                "job_name": job_name,
                "provider": provider,
                "dataset_name": dataset_name,
                "trading_day": trading_day,
                "start_date": start_date,
                "end_date": end_date,
                "asset": asset,
                "freq": freq,
                "request": _json_dump(request or {}),
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
    warning_count: int = 0,
    checkpoint: Mapping[str, Any] | None = None,
) -> None:
    """Finish an ETL run audit row.

    Args:
        conn: Active SQLAlchemy connection.
        run_id: Audit row identifier.
        status: Final job status.
        rows_written: Number of rows written by this run.
        error: Optional failure message.
        warning_count: Number of warnings produced by the run.
        checkpoint: JSON-serializable final checkpoint payload.

    Time Complexity:
        O(1).
    Space Complexity:
        O(c), where c is the serialized checkpoint payload size.
    """

    conn.execute(
        text(
            """
            UPDATE ops.etl_job_run
            SET status = :status,
                rows_written = :rows_written,
                warning_count = :warning_count,
                checkpoint = CAST(:checkpoint AS jsonb),
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
            "warning_count": warning_count,
            "checkpoint": _json_dump(checkpoint or {}),
        },
    )


def _json_dump(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
