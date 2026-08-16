"""批量 upsert：临时表 + COPY + INSERT ... ON CONFLICT。

流程（单事务）：
1. 建与目标表同结构的临时表（仅取规范列）。
2. COPY 把行写入临时表（高效批量加载）。
3. INSERT INTO 目标表 SELECT FROM 临时表 ON CONFLICT 更新。

只操作 contract 声明的规范列；updated_at 由 DB 默认/触发器维护或在 SET 中刷新。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import psycopg

from getrich_data.common.contracts import TableContract


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
    cols = list(columns or contract.columns)
    if not rows:
        return 0

    col_idents = ", ".join(f'"{c}"' for c in cols)
    tmp = f"_stage_{contract.table}"

    update_cols = [c for c in cols if c not in contract.conflict_keys]
    set_clause = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)
    conflict = ", ".join(f'"{c}"' for c in contract.conflict_keys)

    with conn.cursor() as cur:
        cur.execute(
            f'CREATE TEMP TABLE "{tmp}" '
            f"(LIKE {contract.qualified} INCLUDING DEFAULTS) ON COMMIT DROP"
        )
        # 临时表继承了目标表所有列；COPY 只填规范列。
        copy_sql = f'COPY "{tmp}" ({col_idents}) FROM STDIN'
        with cur.copy(copy_sql) as cp:
            for row in rows:
                cp.write_row(row)

        if set_clause:
            on_conflict = f"ON CONFLICT ({conflict}) DO UPDATE SET {set_clause}"
        else:
            on_conflict = f"ON CONFLICT ({conflict}) DO NOTHING"

        cur.execute(
            f"INSERT INTO {contract.qualified} ({col_idents}) "
            f'SELECT {col_idents} FROM "{tmp}" '
            f"{on_conflict}"
        )
        return cur.rowcount
