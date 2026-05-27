from __future__ import annotations

import uuid
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection


def make_engine(database_url: str) -> Engine:
    return create_engine(database_url, future=True, pool_pre_ping=True)


def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def split_table(table: str) -> tuple[str, str]:
    schema, _, name = table.partition(".")
    if not name:
        raise ValueError(f"table must be schema-qualified: {table}")
    return schema, name


def qualified(table: str) -> str:
    schema, name = split_table(table)
    return f"{qident(schema)}.{qident(name)}"


def table_exists(conn: Connection, table: str) -> bool:
    schema, name = split_table(table)
    return bool(
        conn.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = :schema AND table_name = :name
                )
                """
            ),
            {"schema": schema, "name": name},
        ).scalar()
    )


def table_columns(conn: Connection, table: str) -> list[str]:
    schema, name = split_table(table)
    rows = conn.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = :schema AND table_name = :name
            ORDER BY ordinal_position
            """
        ),
        {"schema": schema, "name": name},
    ).scalars()
    return list(rows)


def target_empty(conn: Connection, table: str) -> bool:
    if not table_exists(conn, table):
        return True
    return not bool(conn.execute(text(f"SELECT 1 FROM {qualified(table)} LIMIT 1")).first())


def max_value(conn: Connection, table: str, column: str) -> object | None:
    if not table_exists(conn, table):
        return None
    return conn.execute(text(f"SELECT max({qident(column)}) FROM {qualified(table)}")).scalar()


def delete_all(conn: Connection, table: str) -> None:
    conn.execute(text(f"DELETE FROM {qualified(table)}"))


def execute_sql_files(engine: Engine, sql_dir: Path, file_names: Iterable[str]) -> None:
    with engine.begin() as conn:
        for name in file_names:
            path = sql_dir / name
            sql = path.read_text(encoding="utf-8")
            conn.exec_driver_sql(sql)


def upsert_dataframe(
    conn: Connection,
    df: pd.DataFrame,
    table: str,
    primary_keys: Sequence[str],
    batch_rows: int,
) -> int:
    if df.empty:
        return 0

    target_cols = table_columns(conn, table)
    cols = [c for c in df.columns if c in target_cols]
    missing_pks = [c for c in primary_keys if c not in cols]
    if missing_pks:
        raise ValueError(f"{table}: missing primary key columns: {missing_pks}")

    out = df.loc[:, cols].copy()
    tmp_name = f"tmp_import_{uuid.uuid4().hex[:12]}"
    safe_chunksize = min(batch_rows, max(1, 60_000 // max(1, len(cols))))
    out.to_sql(
        tmp_name,
        con=conn,
        schema="pg_temp",
        if_exists="replace",
        index=False,
        chunksize=safe_chunksize,
        method="multi",
    )

    col_sql = ", ".join(qident(c) for c in cols)
    tmp_sql = f"pg_temp.{qident(tmp_name)}"
    pk_sql = ", ".join(qident(c) for c in primary_keys)
    update_cols = [c for c in cols if c not in primary_keys]
    if update_cols:
        set_sql = ", ".join(f"{qident(c)} = EXCLUDED.{qident(c)}" for c in update_cols)
        if "updated_at" in target_cols and "updated_at" not in cols:
            set_sql += ", updated_at = NOW()"
        conflict_sql = f"DO UPDATE SET {set_sql}"
    else:
        conflict_sql = "DO NOTHING"

    conn.execute(
        text(
            f"""
            INSERT INTO {qualified(table)} ({col_sql})
            SELECT {col_sql}
            FROM {tmp_sql}
            ON CONFLICT ({pk_sql}) {conflict_sql}
            """
        )
    )
    return len(out)
