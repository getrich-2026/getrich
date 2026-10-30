"""`fundamental` schema 的表契约。DDL 真源：gr-db `ddl/postgres/038_fundamental.sql`。"""

from __future__ import annotations

from gr_data.common.contracts.base import TableContract


# tushare daily_basic 的唯一落库位置：源字段一个只落一处，单位在 ingest 层一次归一。
_VALUATION_NUMERIC = (
    "total_mv",
    "circ_mv",
    "pe",
    "pe_ttm",
    "pb",
    "ps",
    "ps_ttm",
    "dv_ratio",
    "dv_ttm",
    "total_share",
    "float_share",
    "free_share",
    "turnover_rate",
    "turnover_rate_f",
    "volume_ratio",
)

VALUATION_1D = TableContract(
    schema="fundamental",
    table="valuation_1d",
    columns=(
        "instrument_id",
        "trading_day",
        *_VALUATION_NUMERIC,
        "limit_status",
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
        *((name, "float8") for name in _VALUATION_NUMERIC),
        ("limit_status", "int2"),
        ("currency", "text"),
        ("source", "text"),
        ("available_at", "timestamptz"),
    ),
)
