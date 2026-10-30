"""`meta` schema 的表契约。DDL 真源：gr-db `ddl/postgres/002_meta.sql`。"""

from __future__ import annotations

from gr_data.common.contracts.base import TableContract


TRADING_CALENDAR = TableContract(
    schema="meta",
    table="trading_calendar",
    columns=(
        "exchange",
        "trading_day",
        "is_open",
        "has_night",
        "prev_trading_day",
        "next_trading_day",
    ),
    conflict_keys=("exchange", "trading_day"),
)

INSTRUMENTS = TableContract(
    schema="meta",
    table="instruments",
    columns=("symbol", "asset", "exchange", "name", "list_date", "delist_date", "status"),
    # 注意冲突键是 DDL 里的 UNIQUE (asset, exchange, symbol)，不是 BIGSERIAL 主键。
    conflict_keys=("asset", "exchange", "symbol"),
)

SYMBOL_MAP = TableContract(
    schema="meta",
    table="symbol_map",
    columns=("instrument_id", "source", "source_symbol"),
    conflict_keys=("source", "source_symbol"),
)

OPTION_CONTRACTS = TableContract(
    schema="meta",
    table="option_contracts",
    columns=(
        "instrument_id",
        "underlying_id",
        "option_type",
        "exercise_style",
        "strike",
        "multiplier",
        "list_date",
        "last_trade_date",
        "exercise_date",
    ),
    conflict_keys=("instrument_id",),
)


# ---- 标的档案（tushare 主数据快照里 meta.instruments 放不下的字段）----
# 档案列多为可空文本，首行全 NULL 时 psycopg 的类型推断会退化，所以显式声明全部类型。
def _profile(table: str, typed: tuple[tuple[str, str], ...]) -> TableContract:
    columns = ("instrument_id", *(name for name, _ in typed), "source")
    return TableContract(
        schema="meta",
        table=table,
        columns=columns,
        conflict_keys=("instrument_id",),
        column_types=(("instrument_id", "int8"), *typed, ("source", "text")),
    )


STOCK_PROFILE = _profile(
    "stock_profile",
    (
        ("fullname", "text"),
        ("enname", "text"),
        ("cnspell", "text"),
        ("area", "text"),
        ("industry", "text"),
        ("board", "text"),
        ("is_hs", "text"),
        ("currency", "text"),
        ("act_name", "text"),
        ("act_ent_type", "text"),
    ),
)

INDEX_PROFILE = _profile(
    "index_profile",
    (
        ("fullname", "text"),
        ("publish_market", "text"),
        ("publisher", "text"),
        ("index_type", "text"),
        ("category", "text"),
        ("base_date", "date"),
        ("base_point", "float8"),
        ("weight_rule", "text"),
        ("description", "text"),
    ),
)

FUTURE_PROFILE = _profile(
    "future_profile",
    (
        ("product_code", "text"),
        ("trade_unit", "text"),
        ("per_unit", "float8"),
        ("quote_unit", "text"),
        ("quote_unit_desc", "text"),
        ("delivery_mode", "text"),
        ("delivery_month", "text"),
        ("delivery_date", "date"),
        ("trade_time_desc", "text"),
    ),
)
