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
