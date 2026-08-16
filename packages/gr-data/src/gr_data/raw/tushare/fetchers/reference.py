"""Tushare raw fetchers：标的与交易日历。

落盘原样保留接口字段，不归一化（归一化在 ingest 层）。

- InstrumentsFetcher : stock_basic / index_basic / fut_basic → instruments/<asset>.parquet
- CalendarFetcher    : trade_cal                            → calendar/<exchange>.parquet
"""

from __future__ import annotations

import pandas as pd

from gr_data.common.parquet import write_parquet
from gr_data.common.retry import int_to_date, retry_call, sleep_s, today_int
from gr_data.raw.base import BaseFetcher


PROVIDER = "tushare"

CALENDAR_EXCHANGES = ("SSE", "SZSE")
# stock_basic 默认只返回上市中(L)的股票；退市(D)与暂停上市(P)必须显式拉取，
# 否则历史行情会因为找不到标的而整段丢失。
STOCK_STATUSES = ("L", "D", "P")
INDEX_MARKETS = ("SSE", "SZSE", "CSI", "SW", "MSCI", "CICC", "OTH")
FUTURE_EXCHANGES = ("CFFEX", "DCE", "CZCE", "SHFE", "INE", "GFEX")
# 1=普通合约, 2=主力与连续合约
FUTURE_TYPES = ("1", "2")

STOCK_BASIC_FIELDS = "ts_code,symbol,name,exchange,curr_type,list_status,list_date,delist_date"
INDEX_BASIC_FIELDS = "ts_code,name,fullname,market,list_date,exp_date"
FUT_BASIC_FIELDS = "ts_code,symbol,exchange,name,fut_code,multiplier,list_date,delist_date"
TRADE_CAL_FIELDS = "exchange,cal_date,is_open,pretrade_date"

CALENDAR_INIT_START = 20130101


class InstrumentsFetcher(BaseFetcher):
    """股票/指数/期货标的清单。"""

    PROVIDER = PROVIDER
    DATASET = "instruments"

    def fetch(self, mode: str = "update") -> int:
        n = 0
        for asset, frame in (
            ("stock", self._stock()),
            ("index", self._index()),
            ("future", self._future()),
        ):
            if frame.empty:
                self.log.warning("instruments[%s] 无数据，跳过写入", asset)
                continue
            out = self.paths.dataset_file(self.PROVIDER, self.DATASET, asset)
            write_parquet(frame, out, append=False)
            self.log.info("instruments[%s] 写入 %d 行", asset, len(frame))
            n += 1
        return n

    def _collect(self, api_name: str, fields: str, param_sets: list[dict]) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for params in param_sets:
            df = retry_call(
                self.client.query_all,
                api_name,
                max_retries=self.ctx.max_retries,
                backoff_base=self.ctx.backoff_base,
                logger=self.log,
                fields=fields,
                **params,
            )
            if df is not None and not df.empty:
                frames.append(df)
            sleep_s(self.ctx.sleep_between_requests)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, axis=0, ignore_index=True)

    def _stock(self) -> pd.DataFrame:
        return self._collect(
            "stock_basic",
            STOCK_BASIC_FIELDS,
            [{"list_status": s} for s in STOCK_STATUSES],
        )

    def _index(self) -> pd.DataFrame:
        return self._collect(
            "index_basic",
            INDEX_BASIC_FIELDS,
            [{"market": m} for m in INDEX_MARKETS],
        )

    def _future(self) -> pd.DataFrame:
        return self._collect(
            "fut_basic",
            FUT_BASIC_FIELDS,
            [{"exchange": e, "fut_type": t} for e in FUTURE_EXCHANGES for t in FUTURE_TYPES],
        )


class CalendarFetcher(BaseFetcher):
    """交易日历。按交易所各落一个文件。"""

    PROVIDER = PROVIDER
    DATASET = "calendar"

    def fetch(self, mode: str = "update") -> int:
        start = int_to_date(self.ctx.start_date or CALENDAR_INIT_START)
        # 多取一年缓冲，供 ingest 推导区间尾部的 next_trading_day
        end = int_to_date(today_int()).replace(year=int_to_date(today_int()).year + 1)
        n = 0
        for exchange in CALENDAR_EXCHANGES:
            df = retry_call(
                self.client.query_all,
                "trade_cal",
                max_retries=self.ctx.max_retries,
                backoff_base=self.ctx.backoff_base,
                logger=self.log,
                exchange=exchange,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                fields=TRADE_CAL_FIELDS,
            )
            if df is None or df.empty:
                self.log.warning("calendar[%s] 无数据，跳过写入", exchange)
                sleep_s(self.ctx.sleep_between_requests)
                continue
            out = self.paths.dataset_file(self.PROVIDER, self.DATASET, exchange)
            write_parquet(df, out, append=False)
            self.log.info("calendar[%s] 写入 %d 行", exchange, len(df))
            n += 1
            sleep_s(self.ctx.sleep_between_requests)
        return n
