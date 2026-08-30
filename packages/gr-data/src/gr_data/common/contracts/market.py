"""`market` schema 的表契约。

DDL 真源：gr-db `ddl/postgres/003_market.sql`（K 线）、`007_insight.sql`
（复权因子 / 每日指标 / 估值等参考表）、`036_market_ext.sql`（复权因子明细）。
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


# ---- 参考表 ----
# 表结构是 insight 时代定的（OHLC + 换手 + 市值），而 tushare `daily_basic`
# 返回的是估值口径（pe/pb/ps/dv/股本）。两边只在 close / turnover_rate /
# 两个市值列上重合，其余 tushare 字段进 raw_payload —— 面向分析的规整形态
# 在 `fundamental.valuation_1d`，不在这里。
STOCK_DAILY_BASIC = TableContract(
    schema="market",
    table="stock_daily_basic",
    columns=(
        "instrument_id",
        "trading_day",
        "close",
        "turnover_rate",
        "float_market_cap",
        "total_market_cap",
        "source",
        "raw_payload",
    ),
    conflict_keys=("instrument_id", "trading_day", "source"),
    # 声明的是**发送端的线上类型**，不是目标列的 PG 类型：这几列在表里是
    # NUMERIC，但 Python 侧给的是 float，声明 numeric 会让 psycopg 选中
    # NumericDumper 而它不接受 float。float8 的文本表示能被 NUMERIC 原样解析。
    column_types=(
        ("instrument_id", "int8"),
        ("trading_day", "date"),
        ("close", "float8"),
        ("turnover_rate", "float8"),
        ("float_market_cap", "float8"),
        ("total_market_cap", "float8"),
        ("source", "text"),
        ("raw_payload", "jsonb"),
    ),
)

# 每日单值复权因子的明细表（tushare `adj_factor`）。canonical 的
# `market.*_bar_1d.adj_factor` 列仍然照填，这张表存的是不依赖行情表的原始序列。
ADJ_FACTOR_TS = TableContract(
    schema="market",
    table="adj_factor_ts",
    columns=("instrument_id", "trading_day", "adj_factor", "source"),
    conflict_keys=("instrument_id", "trading_day", "source"),
)
