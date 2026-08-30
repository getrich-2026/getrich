"""`classify` schema 的表契约。DDL 真源：gr-db `ddl/postgres/039_classify.sql`。"""

from __future__ import annotations

from gr_data.common.contracts.base import TableContract


SCHEME = TableContract(
    schema="classify",
    table="scheme",
    columns=("scheme_code", "scheme_name", "max_level", "available_level", "source"),
    conflict_keys=("scheme_code",),
)

INDUSTRY_NODE = TableContract(
    schema="classify",
    table="industry_node",
    columns=(
        "scheme_code",
        "level",
        "industry_code",
        "industry_name",
        "parent_code",
        "external_code",
    ),
    conflict_keys=("scheme_code", "level", "industry_code"),
)

# valid_range 是 GENERATED ALWAYS 列，**不能出现在 columns 里** —— 往生成列
# INSERT 会直接报错。它由 (in_date, out_date) 派生，写这两列就够了。
INSTRUMENT_INDUSTRY = TableContract(
    schema="classify",
    table="instrument_industry",
    columns=(
        "instrument_id",
        "scheme_code",
        "level",
        "industry_code",
        "in_date",
        "out_date",
        "available_at",
        "source",
    ),
    conflict_keys=("instrument_id", "scheme_code", "level", "in_date"),
    column_types=(
        ("instrument_id", "int8"),
        ("scheme_code", "text"),
        ("level", "int2"),
        ("industry_code", "text"),
        ("in_date", "date"),
        ("out_date", "date"),
        ("available_at", "timestamptz"),
        ("source", "text"),
    ),
)

INSTRUMENT_CATEGORY = TableContract(
    schema="classify",
    table="instrument_category",
    columns=(
        "instrument_id",
        "asset_category",
        "market",
        "in_date",
        "out_date",
        "available_at",
        "source",
    ),
    conflict_keys=("instrument_id", "in_date"),
    column_types=(
        ("instrument_id", "int8"),
        ("asset_category", "text"),
        ("market", "text"),
        ("in_date", "date"),
        ("out_date", "date"),
        ("available_at", "timestamptz"),
        ("source", "text"),
    ),
)
