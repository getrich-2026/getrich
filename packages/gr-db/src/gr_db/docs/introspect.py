"""从活库 catalog 读取 PostgreSQL 与 ClickHouse 的表元数据。"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .model import ColumnDoc, SchemaDoc, TableDoc


def _fetchall(conn: Any, sql: str) -> list[tuple[Any, ...]]:
    """执行查询并获取结果。

    Time Complexity: O(n)，其中 n 为查询返回行数。
    Space Complexity: O(n)。
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        return list(cur.fetchall())


_PG_TABLES_SQL = """
SELECT n.nspname, c.relname, obj_description(c.oid, 'pg_class'),
       c.reltuples::bigint, pg_total_relation_size(c.oid)::bigint
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p')
  AND n.nspname IN (
      'app', 'backtest', 'classify', 'factor', 'fundamental', 'market',
      'meta', 'ops', 'pick', 'realtime', 'staging'
  )
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
  AND n.nspname IN (
      'app', 'backtest', 'classify', 'factor', 'fundamental', 'market',
      'meta', 'ops', 'pick', 'realtime', 'staging'
  )
ORDER BY n.nspname, c.relname, a.attnum
"""
_PG_CONSTRAINTS_SQL = """
SELECT n.nspname, c.relname, con.conname, pg_get_constraintdef(con.oid)
FROM pg_constraint con
JOIN pg_class c ON c.oid = con.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname IN (
    'app', 'backtest', 'classify', 'factor', 'fundamental', 'market',
    'meta', 'ops', 'pick', 'realtime', 'staging'
)
ORDER BY n.nspname, c.relname, con.conname
"""
_PG_INDEXES_SQL = """
SELECT n.nspname, c.relname, i.relname, pg_get_indexdef(i.oid)
FROM pg_index ix
JOIN pg_class c ON c.oid = ix.indrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_class i ON i.oid = ix.indexrelid
LEFT JOIN pg_constraint con ON con.conindid = i.oid
WHERE con.oid IS NULL
  AND n.nspname IN (
      'app', 'backtest', 'classify', 'factor', 'fundamental', 'market',
      'meta', 'ops', 'pick', 'realtime', 'staging'
  )
ORDER BY n.nspname, c.relname, i.relname
"""
_PG_HYPERTABLES_SQL = """
SELECT h.hypertable_schema, h.hypertable_name,
       COALESCE(string_agg(d.column_name, ', ' ORDER BY d.dimension_number), ''),
       CASE WHEN h.compression_enabled THEN 'enabled' ELSE 'disabled' END
FROM timescaledb_information.hypertables h
LEFT JOIN timescaledb_information.dimensions d
  ON d.hypertable_schema = h.hypertable_schema AND d.hypertable_name = h.hypertable_name
GROUP BY h.hypertable_schema, h.hypertable_name, h.compression_enabled
"""


def introspect_postgres(conn: Any) -> tuple[SchemaDoc, ...]:
    """读取 PostgreSQL 的表、列、约束、索引和 Timescale 元数据。

    Timescale 扩展不存在时自动退化，仍返回普通表信息。

    Time Complexity: O(t + c + k + i)，分别为表、列、约束和索引数。
    Space Complexity: O(t + c + k + i)。
    """
    table_rows = _fetchall(conn, _PG_TABLES_SQL)
    columns: dict[tuple[str, str], list[ColumnDoc]] = defaultdict(list)
    constraints: dict[tuple[str, str], list[str]] = defaultdict(list)
    indexes: dict[tuple[str, str], list[str]] = defaultdict(list)
    for schema, table, name, data_type, nullable, default, comment in _fetchall(
        conn, _PG_COLUMNS_SQL
    ):
        columns[(schema, table)].append(ColumnDoc(name, data_type, nullable, default, comment))
    for schema, table, name, definition in _fetchall(conn, _PG_CONSTRAINTS_SQL):
        constraints[(schema, table)].append(f"{name}: {definition}")
    for schema, table, name, definition in _fetchall(conn, _PG_INDEXES_SQL):
        indexes[(schema, table)].append(f"{name}: {definition}")

    hypertables: dict[tuple[str, str], tuple[str, str | None]] = {}
    try:
        for schema, table, dimensions, compression in _fetchall(conn, _PG_HYPERTABLES_SQL):
            hypertables[(schema, table)] = (dimensions or "hypertable", compression or None)
    except Exception:  # 扩展在本地开发库可能不存在。
        pass

    grouped: dict[str, list[TableDoc]] = defaultdict(list)
    for schema, table, comment, row_estimate, total_bytes in table_rows:
        dimension, compression = hypertables.get((schema, table), (None, None))
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
SELECT database, table, name, type, comment
FROM system.columns
WHERE database NOT IN ('system', 'information_schema', 'INFORMATION_SCHEMA')
ORDER BY database, table, position
"""


def introspect_clickhouse(client: Any) -> tuple[TableDoc, ...]:
    """读取 ClickHouse 的表与列 catalog。

    Time Complexity: O(t + c)，其中 t 为表数、c 为列数。
    Space Complexity: O(t + c)。
    """
    table_rows = list(client.query(_CH_TABLES_SQL).result_rows)
    columns: dict[tuple[str, str], list[ColumnDoc]] = defaultdict(list)
    for database, table, name, data_type, comment in client.query(_CH_COLUMNS_SQL).result_rows:
        columns[(database, table)].append(ColumnDoc(name, data_type, True, comment=comment or None))
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
