"""Canonical 表契约。

定义入库目标表的「规范列」，是 ingest transform 的输出标准，与 db/ddl 严格对齐。
若 DDL 变更，必须同步本文件（见 docs/conventions/naming.md）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TableContract:
    """一张目标表的契约。"""

    schema: str
    table: str
    columns: tuple[str, ...]          # 规范列（不含 DB 自动维护的 updated_at）
    conflict_keys: tuple[str, ...]    # ON CONFLICT 键（= 业务主键）

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.table}"


# ---- meta ----
TRADING_CALENDAR = TableContract(
    schema="meta",
    table="trading_calendar",
    columns=("exchange", "trading_day", "is_open", "has_night", "prev_trading_day", "next_trading_day"),
    conflict_keys=("exchange", "trading_day"),
)

INSTRUMENTS = TableContract(
    schema="meta",
    table="instruments",
    columns=("symbol", "asset", "exchange", "name", "list_date", "delist_date", "status"),
    conflict_keys=("asset", "exchange", "symbol"),
)

SYMBOL_MAP = TableContract(
    schema="meta",
    table="symbol_map",
    columns=("instrument_id", "source", "source_symbol"),
    conflict_keys=("source", "source_symbol"),
)


# ---- market: 日线/分钟线 ----
_BAR_1D_BASE = ("instrument_id", "dt", "trading_day", "open", "high", "low", "close",
                "pre_close", "volume", "amount", "limit_up", "limit_down",
                "trading_status", "adj_factor", "source")
_BAR_1M_BASE = ("instrument_id", "dt", "trading_day", "open", "high", "low", "close",
                "pre_close", "volume", "amount", "limit_up", "limit_down",
                "trading_status", "source")
_DERIV_EXTRA = ("open_interest", "settle", "pre_settle")

VALID_ASSETS = ("stock", "etf", "index", "future", "option", "fund")


def bar_1d(asset: str) -> TableContract:
    """日线表契约。asset ∈ {stock, etf, index, future, option}。"""
    cols = _BAR_1D_BASE
    if asset in ("future", "option"):
        # 衍生品无 adj_factor，但有持仓/结算列
        cols = tuple(c for c in _BAR_1D_BASE if c != "adj_factor") + _DERIV_EXTRA
    return TableContract(
        schema="market",
        table=f"{asset}_bar_1d",
        columns=cols,
        conflict_keys=("instrument_id", "dt"),
    )


def bar_1m(asset: str) -> TableContract:
    cols = _BAR_1M_BASE
    if asset in ("future", "option"):
        cols = _BAR_1M_BASE + _DERIV_EXTRA
    return TableContract(
        schema="market",
        table=f"{asset}_bar_1m",
        columns=cols,
        conflict_keys=("instrument_id", "dt"),
    )
