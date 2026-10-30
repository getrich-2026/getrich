"""从活库 catalog 读取 PostgreSQL 与 ClickHouse 的表元数据。"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from psycopg import errors as pg_errors

from .model import ColumnDoc, SchemaDoc, TableDoc


logger = logging.getLogger(__name__)

PG_SCHEMAS = (
    "app",
    "backtest",
    "classify",
    "diag",
    "factor",
    "fundamental",
    "market",
    "meta",
    "ops",
    "pick",
    "realtime",
    "staging",
)
"""gr-db 管理的业务 schema；不含 TimescaleDB 内部 schema。新增 schema 只改这里。"""

# TimescaleDB 未安装或版本缺少相关函数时的 catalog 错误；其余错误照常上抛。
_TIMESCALE_MISSING = (
    pg_errors.UndefinedTable,
    pg_errors.UndefinedFunction,
    pg_errors.InvalidSchemaName,
)


def _fetchall(conn: Any, sql: str, params: Sequence[Any] | None = None) -> list[tuple[Any, ...]]:
    """执行查询并获取结果。

    Time Complexity: O(n)，其中 n 为查询返回行数。
    Space Complexity: O(n)。
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


# 从未 ANALYZE 的表 reltuples 为 -1（PG14+），按未知处理。
_PG_TABLES_SQL = """
SELECT n.nspname, c.relname, obj_description(c.oid, 'pg_class'),
       CASE WHEN c.reltuples < 0 THEN NULL ELSE c.reltuples::bigint END,
       pg_total_relation_size(c.oid)::bigint
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p') AND n.nspname = ANY(%s)
ORDER BY n.nspname, c.relname
"""
_PG_COLUMNS_SQL = """
SELECT n.nspname, c.relname, a.attname, format_type(a.atttypid, a.atttypmod),
       NOT a.attnotnull, pg_get_expr(ad.adbin, ad.adrelid),
       col_description(c.oid, a.attnum)
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_attrdef ad ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
WHERE c.relkind IN ('r', 'p') AND a.attnum > 0 AND NOT a.attisdropped
  AND n.nspname = ANY(%s)
ORDER BY n.nspname, c.relname, a.attnum
"""
_PG_CONSTRAINTS_SQL = """
SELECT n.nspname, c.relname, con.conname, pg_get_constraintdef(con.oid)
FROM pg_constraint con
JOIN pg_class c ON c.oid = con.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = ANY(%s)
ORDER BY n.nspname, c.relname, con.conname
"""
_PG_INDEXES_SQL = """
SELECT n.nspname, c.relname, i.relname, pg_get_indexdef(i.oid)
FROM pg_index ix
JOIN pg_class c ON c.oid = ix.indrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_class i ON i.oid = ix.indexrelid
LEFT JOIN pg_constraint con ON con.conindid = i.oid
WHERE con.oid IS NULL AND n.nspname = ANY(%s)
ORDER BY n.nspname, c.relname, i.relname
"""
# 超表数据都在 chunk 中，父表的 reltuples 与 pg_total_relation_size 接近 0，
# 必须改用 Timescale 的 approximate_row_count / hypertable_size。
_PG_HYPERTABLES_SQL = """
SELECT h.hypertable_schema, h.hypertable_name,
       COALESCE(string_agg(d.column_name, ', ' ORDER BY d.dimension_number), ''),
       CASE WHEN h.compression_enabled THEN 'enabled' ELSE 'disabled' END,
       approximate_row_count(
           (quote_ident(h.hypertable_schema) || '.' || quote_ident(h.hypertable_name))::regclass
       ),
       hypertable_size(
           (quote_ident(h.hypertable_schema) || '.' || quote_ident(h.hypertable_name))::regclass
       )
FROM timescaledb_information.hypertables h
LEFT JOIN timescaledb_information.dimensions d
  ON d.hypertable_schema = h.hypertable_schema AND d.hypertable_name = h.hypertable_name
WHERE h.hypertable_schema = ANY(%s)
GROUP BY h.hypertable_schema, h.hypertable_name, h.compression_enabled
"""


def _fetch_hypertables(
    conn: Any,
) -> dict[tuple[str, str], tuple[str, str | None, int | None, int | None]]:
    """读取超表维度、压缩状态和按 chunk 汇总的行数与大小。

    TimescaleDB 未安装时返回空字典并记 WARNING；其余错误上抛。

    Time Complexity: O(h)，h 为超表数。
    Space Complexity: O(h)。
    """
    try:
        rows = _fetchall(conn, _PG_HYPERTABLES_SQL, [list(PG_SCHEMAS)])
    except _TIMESCALE_MISSING as exc:
        logger.warning("timescaledb catalog unavailable, hypertable metadata skipped: %s", exc)
        return {}
    return {
        (schema, table): (dimensions or "hypertable", compression or None, row_count, size)
        for schema, table, dimensions, compression, row_count, size in rows
    }


def introspect_postgres(conn: Any) -> tuple[SchemaDoc, ...]:
    """读取 PostgreSQL 的表、列、约束、索引和 Timescale 元数据。

    超表的行数与大小用 chunk 汇总值替换父表统计。Timescale 扩展不存在时自动退化，
    仍返回普通表信息。

    Args:
        conn: psycopg 连接，须为 autocommit。非 autocommit 时，Timescale 查询失败会
            让事务进入 aborted 状态，同一连接上的后续查询都会失败。

    Time Complexity: O(t + c + k + i)，分别为表、列、约束和索引数。
    Space Complexity: O(t + c + k + i)。
    """
    params = [list(PG_SCHEMAS)]
    table_rows = _fetchall(conn, _PG_TABLES_SQL, params)
    columns: dict[tuple[str, str], list[ColumnDoc]] = defaultdict(list)
    constraints: dict[tuple[str, str], list[str]] = defaultdict(list)
    indexes: dict[tuple[str, str], list[str]] = defaultdict(list)
    for schema, table, name, data_type, nullable, default, comment in _fetchall(
        conn, _PG_COLUMNS_SQL, params
    ):
        columns[(schema, table)].append(ColumnDoc(name, data_type, nullable, default, comment))
    for schema, table, name, definition in _fetchall(conn, _PG_CONSTRAINTS_SQL, params):
        constraints[(schema, table)].append(f"{name}: {definition}")
    for schema, table, name, definition in _fetchall(conn, _PG_INDEXES_SQL, params):
        indexes[(schema, table)].append(f"{name}: {definition}")
    hypertables = _fetch_hypertables(conn)

    grouped: dict[str, list[TableDoc]] = defaultdict(list)
    for schema, table, comment, row_estimate, total_bytes in table_rows:
        hypertable = hypertables.get((schema, table))
        dimension: str | None = None
        compression: str | None = None
        if hypertable is not None:
            dimension, compression, row_estimate, total_bytes = hypertable
        grouped[schema].append(
            TableDoc(
                schema=schema,
                name=table,
                comment=comment,
                columns=tuple(columns[(schema, table)]),
                constraints=tuple(constraints[(schema, table)]),
                indexes=tuple(indexes[(schema, table)]),
                row_estimate=row_estimate,
                total_bytes=total_bytes,
                hypertable=dimension,
                compression=compression,
            )
        )
    return tuple(SchemaDoc(name, tuple(tables)) for name, tables in sorted(grouped.items()))


_CH_TABLES_SQL = """
SELECT database, name, engine, partition_key, sorting_key, comment, total_rows, total_bytes
FROM system.tables
WHERE is_temporary = 0 AND database NOT IN ('system', 'information_schema', 'INFORMATION_SCHEMA')
ORDER BY database, name
"""
_CH_COLUMNS_SQL = """
SELECT database, table, name, type, default_expression, comment
FROM system.columns
WHERE database NOT IN ('system', 'information_schema', 'INFORMATION_SCHEMA')
ORDER BY database, table, position
"""


def _clickhouse_nullable(data_type: str) -> bool:
    """判断 ClickHouse 列本身是否可空。

    ``Array(Nullable(T))`` 这类只是元素可空，列本身不可空，因此只看最外层包装。
    """
    return data_type.startswith(("Nullable(", "LowCardinality(Nullable("))


def introspect_clickhouse(client: Any) -> tuple[TableDoc, ...]:
    """读取 ClickHouse 的表与列 catalog。

    Time Complexity: O(t + c)，其中 t 为表数、c 为列数。
    Space Complexity: O(t + c)。
    """
    table_rows = list(client.query(_CH_TABLES_SQL).result_rows)
    columns: dict[tuple[str, str], list[ColumnDoc]] = defaultdict(list)
    for database, table, name, data_type, default, comment in client.query(
        _CH_COLUMNS_SQL
    ).result_rows:
        columns[(database, table)].append(
            ColumnDoc(
                name,
                data_type,
                _clickhouse_nullable(data_type),
                default=default or None,
                comment=comment or None,
            )
        )
    return tuple(
        TableDoc(
            schema=database,
            name=name,
            engine=engine,
            partition_key=partition_key or None,
            sorting_key=sorting_key or None,
            comment=comment or None,
            row_estimate=rows,
            total_bytes=size,
            columns=tuple(columns[(database, name)]),
        )
        for database, name, engine, partition_key, sorting_key, comment, rows, size in table_rows
    )
