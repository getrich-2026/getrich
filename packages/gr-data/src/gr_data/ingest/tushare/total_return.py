"""DS08 全收益指数快照。只接受指定中证全收益代码和 SSE 开市日历。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import psycopg

from gr_data.common.benchmark import benchmark_version
from gr_data.common.dates import int_to_date, to_int_date
from gr_data.common.ownership import OwnershipManager


TOTAL_RETURN_SYMBOLS = frozenset({"H00300.CSI", "H00905.CSI", "H00852.CSI"})
TARGET = "market.index_total_return_1d"


def index_simple_returns(
    prices: pl.DataFrame, calendar: pl.DataFrame
) -> tuple[str, dict[date, float]]:
    """按相邻开市日收盘指数计算日简单收益，区间首日或前一日缺报价时无收益。"""
    codes = prices["ts_code"].unique().to_list()
    if len(codes) != 1 or codes[0] not in TOTAL_RETURN_SYMBOLS:
        raise ValueError("Expected one supported CSI total-return index")
    if (
        calendar["exchange"].unique().to_list() != ["SSE"]
        or calendar["cal_date"].n_unique() != calendar.height
    ):
        raise ValueError("Expected a unique SSE calendar")
    if prices["trade_date"].n_unique() != prices.height:
        raise ValueError("Duplicate benchmark date")
    if not prices.select(
        (pl.col("close").is_finite() & (pl.col("close") > 0)).fill_null(False).all()
    ).item():
        raise ValueError("Invalid benchmark close")
    civil_days = calendar["cal_date"].str.to_date("%Y%m%d")
    first, last = civil_days.min(), civil_days.max()
    if (
        not isinstance(first, date)
        or not isinstance(last, date)
        or civil_days.null_count()
        or last.toordinal() - first.toordinal() + 1 != calendar.height
        or not set(calendar["is_open"].unique()) <= {0, 1}
    ):
        raise ValueError("Incomplete daily SSE calendar")
    days = (
        calendar.filter(pl.col("is_open") == 1).sort("cal_date").select("cal_date", "pretrade_date")
    )
    open_dates = days["cal_date"].to_list()
    previous_dates = days["pretrade_date"].to_list()
    if previous_dates[1:] != open_dates[:-1]:
        raise ValueError("Inconsistent previous trading day in SSE calendar")
    quotes = dict(prices.select("trade_date", "close").iter_rows())
    if not quotes.keys() <= set(days["cal_date"]):
        raise ValueError("Missing trading calendar coverage")
    returns = {
        int_to_date(to_int_date(day)): quotes[day] / quotes[previous] - 1.0
        for day, previous in zip(open_dates[1:], open_dates[:-1], strict=True)
        if day in quotes and previous in quotes
    }
    if not returns:
        raise ValueError("No consecutive trading days with benchmark prices")
    return codes[0], returns


def import_total_return(
    conn: psycopg.Connection, prices_path: Path, calendar_path: Path
) -> tuple[str, str, int]:
    """原子导入单个 DS08 快照，内容寻址版本可幂等重试，调用者管理提交。"""
    symbol, returns = index_simple_returns(
        pl.read_parquet(prices_path), pl.read_parquet(calendar_path)
    )
    version = benchmark_version(symbol, returns)
    # 054/057 要求 _timescaledb_internal 下所有新建 chunk 自动挂载 diag_chunk_truncate；
    # 独立导入跨年新建 chunk 前必须开启事件触发器，防止发布全局有效性检查永久失败。
    conn.execute("SELECT set_config('timescaledb.enable_event_triggers', 'on', true)")
    conn.execute("LOCK TABLE ops.table_ownership IN SHARE ROW EXCLUSIVE MODE")
    ownership = OwnershipManager(conn)
    if ownership.owner(TARGET) is None:
        ownership.claim(TARGET, "tushare")
    else:
        ownership.check(TARGET, "tushare")
    with conn.cursor() as cur:
        cur.execute(
            """SELECT i.instrument_id FROM meta.symbol_map s
               JOIN meta.instruments i USING (instrument_id)
               WHERE s.source = 'tushare' AND s.source_symbol = %s
                 AND i.asset = 'index' AND i.exchange = 'CSI' AND i.symbol = %s""",
            (symbol, symbol),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Missing admitted Tushare index identity: {symbol}")
        cur.executemany(
            """INSERT INTO market.index_total_return_1d
               (instrument_id,version,dt,simple_return,source) VALUES (%s,%s,%s,%s,'tushare')
               ON CONFLICT (instrument_id,version,dt) DO NOTHING""",
            [(row[0], version, day, value) for day, value in returns.items()],
        )
    return symbol, version, len(returns)
