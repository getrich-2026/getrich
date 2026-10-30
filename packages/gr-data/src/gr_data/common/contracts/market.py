"""`market` schema 的表契约。

DDL 真源：gr-db `ddl/postgres/003_market.sql`（K 线）、`007_insight.sql`
（复权因子等参考表）、`036_market_ext.sql`（复权因子明细）。
"""

from __future__ import annotations

from gr_data.common.contracts.base import TableContract


# ---- 日线 / 分钟线 ----
_BAR_1D_BASE = (
    "instrument_id",
    "dt",
    "trading_day",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "volume",
    "amount",
    "limit_up",
    "limit_down",
    "trading_status",
    "adj_factor",
    "source",
)
_BAR_1M_BASE = (
    "instrument_id",
    "dt",
    "trading_day",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "volume",
    "amount",
    "limit_up",
    "limit_down",
    "trading_status",
    "source",
)
_DERIV_EXTRA = ("open_interest", "settle", "pre_settle")

VALID_ASSETS = ("stock", "etf", "index", "future", "option", "fund")

STOCK_SUSPEND_EVENT = TableContract(
    schema="market",
    table="stock_suspend_event",
    columns=(
        "instrument_id",
        "trading_day",
        "suspend_type",
        "suspend_timing",
        "source_symbol",
        "source",
        "observed_at",
    ),
    conflict_keys=("instrument_id", "trading_day", "suspend_type", "source"),
)
STOCK_SUSPEND_COVERAGE = TableContract(
    schema="market",
    table="stock_suspend_coverage",
    columns=("trading_day", "source", "raw_sha256", "observed_at"),
    conflict_keys=("trading_day", "source"),
)


def bar_1d(asset: str) -> TableContract:
    """日线表契约。asset ∈ {stock, etf, index, future, option}。"""
    cols = _BAR_1D_BASE
    if asset in ("future", "option"):
        # 衍生品无 adj_factor，但有持仓/结算列
        cols = tuple(c for c in _BAR_1D_BASE if c != "adj_factor") + _DERIV_EXTRA
    elif asset == "stock":
        # 045：区分「不设涨跌幅」与「涨跌停价未知」；其他资产表没有该列。
        cols = _BAR_1D_BASE + ("price_limit_status",)
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


# ---- 参考表 ----
# 每日单值复权因子的明细表（tushare `adj_factor`）。canonical 的
# `market.*_bar_1d.adj_factor` 列仍然照填，这张表存的是不依赖行情表的原始序列。
ADJ_FACTOR_TS = TableContract(
    schema="market",
    table="adj_factor_ts",
    columns=("instrument_id", "trading_day", "adj_factor", "source"),
    conflict_keys=("instrument_id", "trading_day", "source"),
)
