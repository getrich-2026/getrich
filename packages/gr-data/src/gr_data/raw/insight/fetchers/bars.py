"""华泰 INSIGHT raw fetchers：基础信息、交易日、日线。

落盘原样保留 SDK 字段，不归一化。
"""

from __future__ import annotations

import pandas as pd

from gr_data.common.parquet import last_index_date, read_parquet_if_exists, write_parquet
from gr_data.common.retry import (
    int_to_date,
    next_int_date,
    retry_call,
    sleep_s,
    today_int,
)
from gr_data.raw.base import BaseFetcher


INIT_START_DATE = 20130101

# INSIGHT security_type / exchange（来自现有代码核对）
SECURITY_TYPES = {
    "stock": "StockA",
    "etf": "FundETF",
    "index": "IndexCN",
}
EXCHANGES = ["XSHG", "XSHE"]


def _ts(int_date: int) -> int:
    """int8 日期 → INSIGHT 期望的毫秒时间戳。"""
    import datetime as dt

    d = int_to_date(int_date)
    return int(dt.datetime(d.year, d.month, d.day).timestamp() * 1000)


class BasicInfoFetcher(BaseFetcher):
    PROVIDER = "insight"
    DATASET = "basic_info"

    def fetch(self, mode: str = "update") -> int:
        n = 0
        for _asset, st in SECURITY_TYPES.items():
            df = retry_call(
                self.client.get_all_basic_info,
                st,
                EXCHANGES,
                max_retries=self.ctx.max_retries,
                backoff_base=self.ctx.backoff_base,
                logger=self.log,
            )
            if df is not None and not df.empty:
                out = self.paths.dataset_file(self.PROVIDER, self.DATASET, st)
                write_parquet(df.reset_index(drop=True), out, append=False)
                self.log.info("basic_info[%s] 写入 %d 行", st, len(df))
                n += 1
            sleep_s(self.ctx.sleep_between_requests)
        return n


class TradingDaysFetcher(BaseFetcher):
    PROVIDER = "insight"
    DATASET = "trading_days"

    def fetch(self, mode: str = "update") -> int:
        n = 0
        window = [_ts(INIT_START_DATE), _ts(today_int())]
        for exch in EXCHANGES:
            df = retry_call(
                self.client.get_trading_days,
                exch,
                window,
                max_retries=self.ctx.max_retries,
                backoff_base=self.ctx.backoff_base,
                logger=self.log,
            )
            if df is not None and not getattr(df, "empty", True):
                out = self.paths.dataset_file(self.PROVIDER, self.DATASET, exch)
                write_parquet(pd.DataFrame(df).reset_index(drop=True), out, append=False)
                self.log.info("trading_days[%s] 写入 %d 行", exch, len(df))
                n += 1
            sleep_s(self.ctx.sleep_between_requests)
        return n


class KlineDayFetcher(BaseFetcher):
    PROVIDER = "insight"
    DATASET = "kline_day"
    FREQUENCY = "daily"
    CODE_CHUNK_SIZE = 50

    def _all_codes(self) -> list[str]:
        codes: list[str] = []
        for st in SECURITY_TYPES.values():
            df = read_parquet_if_exists(self.paths.dataset_file("insight", "basic_info", st))
            if df is not None and "htsc_code" in df.columns:
                codes += [str(c) for c in df["htsc_code"].tolist()]
        return list(dict.fromkeys(codes))

    def _local_last_date(self, code: str) -> int | None:
        code_dir = self.paths.code_dir(self.PROVIDER, self.DATASET, code)
        if not code_dir.exists():
            return None
        latest: int | None = None
        for f in sorted(code_dir.glob("*.parquet")):
            d = last_index_date(read_parquet_if_exists(f))
            if d is not None and (latest is None or d > latest):
                latest = d
        return latest

    def _save(self, code: str, df: pd.DataFrame) -> None:
        if df is None or df.empty or "time" not in df.columns:
            return
        df = df.copy()
        df["time"] = pd.to_datetime(df["time"])
        df = df.set_index("time")
        df = df[~df.index.duplicated(keep="last")].sort_index()
        for ym, grp in df.groupby(df.index.strftime("%Y-%m")):
            out = self.paths.code_month_file(self.PROVIDER, self.DATASET, code, ym)
            write_parquet(grp, out, append=True)

    def fetch(self, mode: str = "update") -> int:
        codes = self._all_codes()
        n = 0
        for code in codes:
            start = INIT_START_DATE
            if self.ctx.start_date:
                start = max(start, int(self.ctx.start_date))
            if mode != "init":
                last = self._local_last_date(code)
                if last:
                    start = max(start, next_int_date(last, 1))
            end = today_int()
            if start > end:
                continue
            df = retry_call(
                self.client.get_kline,
                [code],
                [_ts(start), _ts(end)],
                self.FREQUENCY,
                "none",
                max_retries=self.ctx.max_retries,
                backoff_base=self.ctx.backoff_base,
                logger=self.log,
            )
            self._save(code, df)
            n += 1
            sleep_s(self.ctx.sleep_between_requests)
        self.log.info("kline_day 处理 %d codes", len(codes))
        return n
