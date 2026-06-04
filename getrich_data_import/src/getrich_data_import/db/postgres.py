from __future__ import annotations

from pathlib import Path
from typing import Iterable

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection


SCHEMA_FILES = [
    "00_extensions.sql",
    "10_meta.sql",
    "20_market.sql",
    "30_compress_ca.sql",
    "40_realtime.sql",
    "50_ops.sql",
    "60_review_appendix_a.sql",
]


def make_engine(database_url: str) -> Engine:
    return create_engine(database_url, future=True, pool_pre_ping=True)


def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def qualified(schema: str, table: str) -> str:
    return f"{qident(schema)}.{qident(table)}"


def execute_schema(engine: Engine, sql_dir: Path, files: Iterable[str] = SCHEMA_FILES) -> None:
    with engine.begin() as conn:
        for file_name in files:
            conn.exec_driver_sql((sql_dir / file_name).read_text(encoding="utf-8"))


def table_columns(conn: Connection, schema: str, table: str) -> list[str]:
    return list(
        conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = :schema AND table_name = :table
                ORDER BY ordinal_position
                """
            ),
            {"schema": schema, "table": table},
        ).scalars()
    )


def max_value(conn: Connection, schema: str, table: str, column: str) -> object | None:
    return conn.execute(
        text(f"SELECT max({qident(column)}) FROM {qualified(schema, table)}")
    ).scalar()
