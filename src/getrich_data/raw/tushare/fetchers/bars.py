"""Tushare raw fetchers：日线及其配套的逐日数据集。

全部按**自然月**分区落盘：``<dataset>/<YYYY-MM>.parquet``，每个文件含当月全市场记录。
Tushare 这几个接口都是「按日期区间取全市场」的形态（不需要先有代码清单），
因此按月分区比按 code 分区更省调用次数，也便于断点续传。

- Bars1dFetcher       : daily       → daily/<YYYY-MM>.parquet
- AdjFactorFetcher    : adj_factor  → adj_factor/<YYYY-MM>.parquet
- StockLimitFetcher   : stk_limit   → stk_limit/<YYYY-MM>.parquet
- SuspensionFetcher   : suspend_d   → suspend_d/<YYYY-MM>.parquet
- IndexBars1dFetcher  : index_daily → index_daily/<YYYY-MM>.parquet
- FutureBars1dFetcher : fut_daily   → fut_daily/<YYYY-MM>.parquet
"""

from __future__ import annotations

import calendar as _calendar
from datetime import date

from getrich_data.common.parquet import write_parquet
from getrich_data.common.retry import int_to_date, retry_call, sleep_s, today_int
from getrich_data.raw.base import BaseFetcher

PROVIDER = "tushare"

INIT_START_DATE = 20130101

DAILY_FIELDS = "ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount"
ADJ_FACTOR_FIELDS = "ts_code,trade_date,adj_factor"
STK_LIMIT_FIELDS = "trade_date,ts_code,pre_close,up_limit,down_limit"
SUSPEND_FIELDS = "ts_code,trade_date,suspend_type,suspend_reason"
INDEX_DAILY_FIELDS = "ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount"
FUT_DAILY_FIELDS = (
    "ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,vol,amount,oi"
)


def month_range(start: date, end: date) -> list[tuple[str, date, date]]:
    """产出 [(YYYY-MM, 月初, 月末), ...]，闭区间按自然月切分。

    首月起点与末月终点分别夹到 start / end，避免越界抓取。
    """
    out: list[tuple[str, date, date]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        last_day = _calendar.monthrange(y, m)[1]
        first = max(date(y, m, 1), start)
        last = min(date(y, m, last_day), end)
        out.append((f"{y:04d}-{m:02d}", first, last))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


class _MonthlyFetcher(BaseFetcher):
    """按月分区抓取全市场逐日数据的通用基类。

    子类只需声明 ``DATASET`` / ``API_NAME`` / ``FIELDS``。
    """

    PROVIDER = PROVIDER
    API_NAME: str = ""
    FIELDS: str = ""

    def _existing_months(self) -> set[str]:
        d = self.paths.dataset_dir(self.PROVIDER, self.DATASET)
        if not d.exists():
            return set()
        return {f.stem for f in d.glob("*.parquet")}

    def _months_to_fetch(self, mode: str) -> list[tuple[str, date, date]]:
        start = int_to_date(self.ctx.start_date or INIT_START_DATE)
        months = month_range(start, int_to_date(today_int()))
        if mode == "init":
            return months

        # update：补齐缺失月份，并**重抓最新的已有月份**——当月还在长新数据，
        # 已落盘的文件必然是不完整的。
        existing = self._existing_months()
        newest = max(existing) if existing else None
        return [m for m in months if m[0] not in existing or m[0] == newest]

    def fetch(self, mode: str = "update") -> int:
        n = 0
        for ym, first, last in self._months_to_fetch(mode):
            df = retry_call(
                self.client.query_all,
                self.API_NAME,
                max_retries=self.ctx.max_retries,
                backoff_base=self.ctx.backoff_base,
                logger=self.log,
                start_date=first.strftime("%Y%m%d"),
                end_date=last.strftime("%Y%m%d"),
                fields=self.FIELDS,
            )
            sleep_s(self.ctx.sleep_between_requests)
            if df is None or df.empty:
                # 非交易月（如春节整月休市不存在，但区间可能全是节假日）属正常情况
                self.log.debug("%s[%s] 无数据", self.DATASET, ym)
                continue
            out = self.paths.dataset_file(self.PROVIDER, self.DATASET, ym)
            write_parquet(df, out, append=False)
            self.log.info("%s[%s] 写入 %d 行", self.DATASET, ym, len(df))
            n += 1
        return n


class Bars1dFetcher(_MonthlyFetcher):
    DATASET = "daily"
    API_NAME = "daily"
    FIELDS = DAILY_FIELDS


class AdjFactorFetcher(_MonthlyFetcher):
    DATASET = "adj_factor"
    API_NAME = "adj_factor"
    FIELDS = ADJ_FACTOR_FIELDS


class StockLimitFetcher(_MonthlyFetcher):
    DATASET = "stk_limit"
    API_NAME = "stk_limit"
    FIELDS = STK_LIMIT_FIELDS


class SuspensionFetcher(_MonthlyFetcher):
    DATASET = "suspend_d"
    API_NAME = "suspend_d"
    FIELDS = SUSPEND_FIELDS


class IndexBars1dFetcher(_MonthlyFetcher):
    DATASET = "index_daily"
    API_NAME = "index_daily"
    FIELDS = INDEX_DAILY_FIELDS


class FutureBars1dFetcher(_MonthlyFetcher):
    DATASET = "fut_daily"
    API_NAME = "fut_daily"
    FIELDS = FUT_DAILY_FIELDS
