"""factor 明细行与所属 model_run 的跨表一致性门禁。

047 的 CHECK 只能约束单行：数组形状、元素有限、长度等于本行的 ``factor_count``。
本行 ``factor_count`` 是否等于所属 ``model_run.factor_count`` 跨了两张表，CHECK 表达不了，
不一致时数组会按另一套因子顺序被解读，且不会报错，所以写库前在这里拦住。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

import psycopg

from gr_data.ingest.base import IngestGateError


def check_factor_counts(
    conn: psycopg.Connection, target: str, rows: Iterable[tuple[object, int]]
) -> None:
    """校验每行的 factor_count 等于所属 model_run 的 factor_count。

    Args:
        conn: 与写入同一事务的连接；本事务内刚创建的 model_run 也必须可见。
        target: 目标表全名，只用于报错信息。
        rows: ``(run_id, factor_count)`` 序列；run_id 接受 UUID、带或不带连字符的字符串。

    Raises:
        IngestGateError: 所属 model_run 不存在，或任一行的 factor_count 与之不同。
    """
    expected: dict[str, set[int]] = {}
    for run_id, count in rows:
        expected.setdefault(str(uuid.UUID(str(run_id))), set()).add(int(count))
    if not expected:
        return
    with conn.cursor() as cur:
        cur.execute(
            "SELECT run_id::text, factor_count FROM factor.model_run "
            "WHERE run_id = ANY(%s::uuid[])",
            (sorted(expected),),
        )
        stored = {run_id: int(count) for run_id, count in cur.fetchall()}
    missing = sorted(set(expected) - set(stored))
    if missing:
        raise IngestGateError(
            f"{target}: model_run not found for {len(missing)} run(s), samples {missing[:3]}"
        )
    mismatched = sorted(run for run, counts in expected.items() if counts != {stored[run]})
    if mismatched:
        raise IngestGateError(
            f"{target}: factor_count differs from model_run for {len(mismatched)} run(s), "
            f"samples {mismatched[:3]}"
        )
