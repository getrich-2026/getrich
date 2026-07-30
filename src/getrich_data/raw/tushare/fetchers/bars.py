"""Tushare raw fetchers：日线及其配套的逐日数据集。

## 为什么按「交易日」调用而不是「日期区间」

Tushare 对一次查询的 ``offset`` 有 **100000 的硬上限**（实测：offset=100000 可用，
100001 报「查询数据失败，请确认参数」）。全市场股票约 5300 只，一个自然月约 22 个
交易日 ≈ 11.7 万行，**超过上限就取不全**。

所以这些接口一律按**单个交易日**调用（``trade_date=YYYYMMDD``），每天约 5300 行、
一页取完，永远碰不到 offset 上限。另有一个接口硬性要求如此：``index_daily``
不带 ``ts_code`` 时不接受日期区间，只接受 ``trade_date``。

交易日列表来自 raw 层已落盘的 calendar 数据集，因此**必须先抓 calendar**。

## 落盘

按自然月分区：``<dataset>/<YYYY-MM>.parquet``，每个文件含当月全市场记录。
调用粒度是「天」，存储粒度是「月」——两者独立。

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

import pandas as pd

from getrich_data.common.parquet import read_parquet_if_exists, write_parquet
from getrich_data.common.retry import int_to_date, retry_call, sleep_s, today_int
from getrich_data.raw.base import BaseFetcher

PROVIDER = "tushare"

INIT_START_DATE = 20130101

# 交易日列表取自哪个交易所的日历。沪深交易日相同，取其一即可。
CALENDAR_EXCHANGE = "SSE"

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


class _DailyFetcher(BaseFetcher):
    """按交易日抓取全市场逐日数据、按自然月分区落盘的通用基类。

    子类只需声明 ``DATASET`` / ``API_NAME`` / ``FIELDS``。
    """

    PROVIDER = PROVIDER
    API_NAME: str = ""
    FIELDS: str = ""

    # ---- 交易日 ----
    def _trading_days(self) -> list[date]:
        """从 raw 层 calendar 数据集读出开市日。

        缺失时直接抛错而不是退化成「按自然日遍历」——后者会对着几百个非交易日
        空转请求，既浪费配额，也让「真的没数据」和「日历没抓」变得无法区分。
        """
        path = self.paths.dataset_file(PROVIDER, "calendar", CALENDAR_EXCHANGE)
        cal = read_parquet_if_exists(path)
        if cal is None or cal.empty:
            raise RuntimeError(
                f"缺少交易日历 {path}。请先运行 `getrich raw tushare --only calendar`。"
            )
        open_days = cal[pd.to_numeric(cal["is_open"], errors="coerce") == 1]
        days = pd.to_datetime(open_days["cal_date"], format="%Y%m%d", errors="coerce")
        return sorted({d.date() for d in days if pd.notna(d)})

    # ---- 月份选择 ----
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

    # ---- 抓取 ----
    def _fetch_day(self, day: date) -> pd.DataFrame | None:
        return retry_call(
            self.client.query_all,
            self.API_NAME,
            max_retries=self.ctx.max_retries,
            backoff_base=self.ctx.backoff_base,
            logger=self.log,
            trade_date=day.strftime("%Y%m%d"),
            fields=self.FIELDS,
        )

    def fetch(self, mode: str = "update") -> int:
        trading_days = self._trading_days()
        n = 0
        for ym, first, last in self._months_to_fetch(mode):
            days = [d for d in trading_days if first <= d <= last]
            if not days:
                continue

            frames: list[pd.DataFrame] = []
            for day in days:
                df = self._fetch_day(day)
                sleep_s(self.ctx.sleep_between_requests)
                if df is not None and not df.empty:
                    frames.append(df)

            if not frames:
                # 整月无数据对稀疏数据集（如 suspend_d）是正常的
                self.log.debug("%s[%s] %d 个交易日均无数据", self.DATASET, ym, len(days))
                continue

            out_df = pd.concat(frames, axis=0, ignore_index=True)
            out = self.paths.dataset_file(self.PROVIDER, self.DATASET, ym)
            write_parquet(out_df, out, append=False)
            self.log.info(
                "%s[%s] 写入 %d 行（%d 个交易日）", self.DATASET, ym, len(out_df), len(days)
            )
            n += 1
        return n


class Bars1dFetcher(_DailyFetcher):
    DATASET = "daily"
    API_NAME = "daily"
    FIELDS = DAILY_FIELDS


class AdjFactorFetcher(_DailyFetcher):
    DATASET = "adj_factor"
    API_NAME = "adj_factor"
    FIELDS = ADJ_FACTOR_FIELDS


class StockLimitFetcher(_DailyFetcher):
    DATASET = "stk_limit"
    API_NAME = "stk_limit"
    FIELDS = STK_LIMIT_FIELDS


class SuspensionFetcher(_DailyFetcher):
    DATASET = "suspend_d"
    API_NAME = "suspend_d"
    FIELDS = SUSPEND_FIELDS


class IndexBars1dFetcher(_DailyFetcher):
    DATASET = "index_daily"
    API_NAME = "index_daily"
    FIELDS = INDEX_DAILY_FIELDS


class FutureBars1dFetcher(_DailyFetcher):
    DATASET = "fut_daily"
    API_NAME = "fut_daily"
    FIELDS = FUT_DAILY_FIELDS
