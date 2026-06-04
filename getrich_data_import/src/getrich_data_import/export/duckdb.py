from __future__ import annotations

from pathlib import Path

import pandas as pd


def query_parquet(path: Path, sql: str | None = None) -> pd.DataFrame:
    duckdb = _load_duckdb()
    parquet_path = str(path.expanduser())
    query = sql or "SELECT * FROM read_parquet(?)"
    with duckdb.connect() as conn:
        if sql is None:
            return conn.execute(query, [parquet_path]).fetchdf()
        conn.execute("CREATE OR REPLACE TEMP VIEW bars AS SELECT * FROM read_parquet(?)", [parquet_path])
        return conn.execute(query).fetchdf()


def _load_duckdb():
    try:
        import duckdb
    except ModuleNotFoundError as exc:
        raise RuntimeError("DuckDB support requires installing the optional 'duckdb' package") from exc
    return duckdb
