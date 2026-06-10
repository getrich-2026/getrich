"""银河全量覆盖类 fetchers：交易日历、历史代码表、后复权因子。

落盘原样保留 SDK 字段，不归一化（归一化在 ingest 层）。
"""

from __future__ import annotations

import pandas as pd

from getrich_data.common.parquet import read_parquet_if_exists, write_parquet
from getrich_data.common.retry import chunk_list, retry_call, sleep_s
from getrich_data.raw.base import BaseFetcher

# 银河 security_type 常量（来自现有代码核对）
SECURITY_TYPES = {
    "stock": "EXTRA_STOCK_A_SH_SZ",
    "etf": "EXTRA_ETF",
    "index": "EXTRA_IDNEX_A_SH_SZ",  # 注：SDK 原始拼写如此
}
INIT_START_DATE = 20130101


class CalendarFetcher(BaseFetcher):
    PROVIDER = "yinhe"
    DATASET = "calendar"
    MARKETS = ("SH",)

    def fetch(self, mode: str = "update") -> int:
        n = 0
        for market in self.MARKETS:
            dates = retry_call(
                self.client.get_calendar, market,
                max_retries=self.ctx.max_retries, backoff_base=self.ctx.backoff_base,
                logger=self.log,
            )
            df = pd.DataFrame({"date": [int(d) for d in dates]}).set_index("date")
            out = self.paths.dataset_file(self.PROVIDER, self.DATASET, f"calendar_{market}")
            write_parquet(df, out, append=False)
            self.log.info("calendar[%s] 写入 %d 行 -> %s", market, len(df), out)
            n += 1
            sleep_s(self.ctx.sleep_between_requests)
        return n


class HistCodeListFetcher(BaseFetcher):
    PROVIDER = "yinhe"
    DATASET = "hist_code_list"

    def fetch(self, mode: str = "update") -> int:
        n = 0
        for _asset, st in SECURITY_TYPES.items():
            codes = retry_call(
                self.client.get_code_list, st,
                max_retries=self.ctx.max_retries, backoff_base=self.ctx.backoff_base,
                logger=self.log,
            )
            df = pd.DataFrame({"code": [str(c) for c in codes]})
            out = self.paths.dataset_file(self.PROVIDER, self.DATASET, st)
            write_parquet(df, out, append=False)
            self.log.info("hist_code_list[%s] 写入 %d 行", st, len(df))
            n += 1
            sleep_s(self.ctx.sleep_between_requests)
        return n


class BackwardFactorFetcher(BaseFetcher):
    PROVIDER = "yinhe"
    DATASET = "backward_factor"
    CODE_CHUNK_SIZE = 200

    def _codes_for(self, st: str) -> list[str]:
        path = self.paths.dataset_file("yinhe", "hist_code_list", st)
        df = read_parquet_if_exists(path)
        if df is None or df.empty:
            return [str(c) for c in self.client.get_code_list(st)]
        return [str(c) for c in df["code"].tolist()]

    def fetch(self, mode: str = "update") -> int:
        n = 0
        for _asset, st in SECURITY_TYPES.items():
            codes = self._codes_for(st)
            frames: list[pd.DataFrame] = []
            for chunk in chunk_list(codes, self.CODE_CHUNK_SIZE):
                df = retry_call(
                    self.client.get_backward_factor, chunk,
                    max_retries=self.ctx.max_retries, backoff_base=self.ctx.backoff_base,
                    logger=self.log,
                )
                if df is not None and not df.empty:
                    frames.append(df)
                sleep_s(self.ctx.sleep_between_requests)
            if frames:
                merged = pd.concat(frames, axis=0)
                out = self.paths.dataset_file(self.PROVIDER, self.DATASET, st)
                write_parquet(merged, out, append=False)
                self.log.info("backward_factor[%s] 写入 %d 行", st, len(merged))
                n += 1
        return n
