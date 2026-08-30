"""`fundamental` schema 的表契约。DDL 真源：gr-db `ddl/postgres/038_fundamental.sql`。"""

from __future__ import annotations

from gr_data.common.contracts.base import TableContract


VALUATION_1D = TableContract(
    schema="fundamental",
    table="valuation_1d",
    columns=(
        "instrument_id",
        "trading_day",
        "total_mv",
        "circ_mv",
        "pb",
        "pe_ttm",
        "currency",
        "source",
        "available_at",
    ),
    conflict_keys=("instrument_id", "trading_day"),
    # 目标列是 NUMERIC，但 Python 侧给的是 float，声明 numeric 会选中不接受 float
    # 的 NumericDumper；float8 的文本表示能被 NUMERIC 原样解析。
    column_types=(
        ("instrument_id", "int8"),
        ("trading_day", "date"),
        ("total_mv", "float8"),
        ("circ_mv", "float8"),
        ("pb", "float8"),
        ("pe_ttm", "float8"),
        ("currency", "text"),
        ("source", "text"),
        ("available_at", "timestamptz"),
    ),
)
