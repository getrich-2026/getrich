"""使用临时表和 COPY 批量 upsert；调用方控制外层事务。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.pq import TransactionStatus

from gr_data.common.contracts import TableContract


def upsert_rows(
    conn: psycopg.Connection,
    contract: TableContract,
    rows: Sequence[Sequence[Any]],
    *,
    columns: Sequence[str] | None = None,
) -> int:
    """把 rows 按 contract upsert 进目标表。返回写入行数。

    rows 中每行的列顺序必须与 ``columns``（默认 contract.columns）一致。
    """
    cols = list(contract.columns if columns is None else columns)
    if not rows:
        return 0
    if not cols or len(set(cols)) != len(cols) or any(col not in contract.columns for col in cols):
        raise ValueError("Upsert columns must be distinct contract columns")
    if any(key not in cols for key in contract.conflict_keys):
        raise ValueError("Upsert columns must include all conflict keys")
    if any(len(row) != len(cols) for row in rows):
        raise ValueError("Upsert row width does not match columns")

    table = sql.Identifier(contract.schema, contract.table)
    stage = sql.Identifier(f"_stage_{uuid4().hex}")
    col_sql = sql.SQL(", ").join(map(sql.Identifier, cols))
    conflict_sql = sql.SQL(", ").join(map(sql.Identifier, contract.conflict_keys))
    update_cols = [col for col in cols if col not in contract.conflict_keys]
    if update_cols:
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = EXCLUDED.{}").format(sql.Identifier(col), sql.Identifier(col))
            for col in update_cols
        )
        on_conflict = sql.SQL("DO UPDATE SET {}").format(assignments)
    else:
        on_conflict = sql.SQL("DO NOTHING")

    if not conn.autocommit and conn.info.transaction_status == TransactionStatus.IDLE:
        conn.execute("SELECT 1")  # 由调用方提交外层事务；下方只管理保存点。
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            sql.SQL("CREATE TEMP TABLE {} (LIKE {} INCLUDING DEFAULTS) ON COMMIT DROP").format(
                stage, table
            )
        )
        pg_types = contract.pg_types_for(cols)
        with cur.copy(sql.SQL("COPY {} ({}) FROM STDIN").format(stage, col_sql)) as cp:
            if pg_types is not None:
                cp.set_types(pg_types)
            for row in rows:
                cp.write_row(row)
        cur.execute(
            sql.SQL("INSERT INTO {} ({}) SELECT {} FROM {} ON CONFLICT ({}) {}").format(
                table, col_sql, col_sql, stage, conflict_sql, on_conflict
            )
        )
        written = cur.rowcount
        cur.execute(sql.SQL("DROP TABLE {}").format(stage))
        return written
