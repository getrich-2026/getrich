"""米筐 raw fetchers：标的、交易日历、日线。

落盘原样保留 SDK 字段，不归一化。
- InstrumentsFetcher : all_instruments(type) → instruments/<asset>.parquet
- CalendarFetcher    : get_trading_dates → calendar/<market>.parquet
- Bars1dFetcher      : get_price(frequency='1d') → bars_1d/<asset>/<code>.parquet
"""

from __future__ import annotations

import pandas as pd

from gr_data.common.parquet import read_parquet_if_exists, write_parquet
from gr_data.common.retry import chunk_list, int_to_date, retry_call, sleep_s, today_int
from gr_data.raw.base import BaseFetcher
from gr_data.raw.ricequant.client import RQ_TYPE_MAP


INIT_START_DATE = 20130101
ASSETS = ("stock", "etf", "index")


class InstrumentsFetcher(BaseFetcher):
    PROVIDER = "ricequant"
    DATASET = "instruments"

    def fetch(self, mode: str = "update") -> int:
        n = 0
        for asset in ASSETS:
            rq_type = RQ_TYPE_MAP[asset]
            df = retry_call(
                self.client.all_instruments,
                rq_type,
                self.client.market,
                max_retries=self.ctx.max_retries,
                backoff_base=self.ctx.backoff_base,
                logger=self.log,
            )
            if df is not None and not df.empty:
                out = self.paths.dataset_file(self.PROVIDER, self.DATASET, asset)
                write_parquet(df.reset_index(drop=True), out, append=False)
                self.log.info("instruments[%s] 写入 %d 行", asset, len(df))
                n += 1
            sleep_s(self.ctx.sleep_between_requests)
        return n


class CalendarFetcher(BaseFetcher):
    PROVIDER = "ricequant"
    DATASET = "calendar"

    def fetch(self, mode: str = "update") -> int:
        start = int_to_date(INIT_START_DATE).isoformat()
        end = int_to_date(today_int()).isoformat()
        dates = retry_call(
            self.client.get_trading_dates,
            start,
            end,
            self.client.market,
            max_retries=self.ctx.max_retries,
            backoff_base=self.ctx.backoff_base,
            logger=self.log,
        )
        df = pd.DataFrame({"trading_day": [str(d) for d in dates]})
        out = self.paths.dataset_file(self.PROVIDER, self.DATASET, self.client.market)
        write_parquet(df, out, append=False)
        self.log.info("calendar 写入 %d 行", len(df))
        return 1


class Bars1dFetcher(BaseFetcher):
    PROVIDER = "ricequant"
    DATASET = "bars_1d"
    CODE_CHUNK_SIZE = 100

    def _codes_for(self, asset: str) -> list[str]:
        path = self.paths.dataset_file("ricequant", "instruments", asset)
        df = read_parquet_if_exists(path)
        if df is None or df.empty or "order_book_id" not in df.columns:
            return []
        return [str(c) for c in df["order_book_id"].tolist()]

    def fetch(self, mode: str = "update") -> int:
        start = int_to_date(INIT_START_DATE).isoformat()
        end = int_to_date(today_int()).isoformat()
        n = 0
        for asset in ASSETS:
            codes = self._codes_for(asset)
            for chunk in chunk_list(codes, self.CODE_CHUNK_SIZE):
                df = retry_call(
                    self.client.get_price,
                    chunk,
                    start,
                    end,
                    "1d",
                    "none",
                    self.client.market,
                    max_retries=self.ctx.max_retries,
                    backoff_base=self.ctx.backoff_base,
                    logger=self.log,
                )
                if df is None or df.empty:
                    sleep_s(self.ctx.sleep_between_requests)
                    continue
                # get_price 多标的返回 MultiIndex(order_book_id, date)；按 code 拆分落盘
                reset = df.reset_index()
                key = "order_book_id" if "order_book_id" in reset.columns else None
                if key is None:
                    sleep_s(self.ctx.sleep_between_requests)
                    continue
                for code, grp in reset.groupby(key):
                    out = self.paths.dataset_file(
                        self.PROVIDER, f"{self.DATASET}/{asset}", str(code)
                    )
                    write_parquet(grp.reset_index(drop=True), out, append=False)
                    n += 1
                sleep_s(self.ctx.sleep_between_requests)
            self.log.info("bars_1d[%s] 处理 %d codes", asset, len(codes))
        return n
