"""Tushare raw fetchers：标的与交易日历。

落盘原样保留接口字段，不归一化（归一化在 ingest 层）。

- InstrumentsFetcher : stock_basic / index_basic / fut_basic → instruments/<asset>.parquet
- CalendarFetcher    : trade_cal                            → calendar/<exchange>.parquet
"""

from __future__ import annotations

import calendar
from datetime import date

import pandas as pd

from gr_data.common.parquet import write_parquet
from gr_data.common.retry import int_to_date, retry_call, sleep_s, today_int
from gr_data.raw.base import BaseFetcher, RawContext
from gr_data.raw.tushare.context import FUTURE_EXCHANGES, INDEX_MARKETS, as_tushare_context


PROVIDER = "tushare"

CALENDAR_EXCHANGES = ("SSE", "SZSE")
# stock_basic 默认只返回上市中(L)的股票；退市(D)与暂停上市(P)必须显式拉取，
# 否则历史行情会因为找不到标的而整段丢失。
STOCK_STATUSES = ("L", "D", "P")
# 1=普通合约, 2=主力与连续合约
FUTURE_TYPES = ("1", "2")

STOCK_BASIC_FIELDS = "ts_code,symbol,name,exchange,curr_type,list_status,list_date,delist_date"
INDEX_BASIC_FIELDS = "ts_code,name,fullname,market,list_date,exp_date"
FUT_BASIC_FIELDS = "ts_code,symbol,exchange,name,fut_code,multiplier,list_date,delist_date"
TRADE_CAL_FIELDS = "exchange,cal_date,is_open,pretrade_date"

CALENDAR_INIT_START = 20130101


def read_open_days(frame: pd.DataFrame, exchange: str) -> list[date]:
    """校验日历键及 0/1 标志，返回有序开市日；坏日历不能解释成休市。"""
    if frame.empty or not {"cal_date", "is_open"} <= set(frame.columns):
        raise ValueError(f"Invalid trading calendar: {exchange}")
    if "exchange" in frame and not frame["exchange"].eq(exchange).all():
        raise ValueError(f"Unexpected trading calendar exchange: {exchange}")
    dates = pd.to_datetime(frame["cal_date"].astype(str), format="%Y%m%d", errors="raise")
    flags = pd.to_numeric(frame["is_open"], errors="coerce")
    if dates.isna().any() or dates.duplicated().any() or not flags.isin([0, 1]).all():
        raise ValueError(f"Invalid trading calendar dates or is_open: {exchange}")
    return sorted(dates.loc[flags.eq(1)].dt.date)


def require_calendar_range(frame: pd.DataFrame, first: date, last: date, exchange: str) -> None:
    """区间内每个自然日须有开闭市记录，缺日期不能被当作休市跳过。"""
    dates = set(pd.to_datetime(frame["cal_date"].astype(str), format="%Y%m%d").dt.date)
    expected = set(pd.date_range(first, last).date)
    missing = sorted(expected - dates)
    if missing:
        raise ValueError(
            f"Incomplete trading calendar exchange={exchange} missing_days={missing[:5]}"
        )


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
            if asset == "stock" and frame["ts_code"].str.endswith(".BJ").any():
                # 供应商历史停复牌仍可能使用旧代码；原样保存官方对照，不推测号段。
                mapping = self._collect("bse_mapping", "name,o_code,n_code,list_date", [{}])
                if mapping.empty or not {"o_code", "n_code"} <= set(mapping.columns):
                    raise ValueError("Missing BSE code mapping")
                write_parquet(
                    mapping, self.paths.dataset_file(self.PROVIDER, self.DATASET, "bse_mapping")
                )
                self.log.info("instruments[bse_mapping] rows=%d", len(mapping))
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
    API_NAME = "trade_cal"
    EXCHANGES = CALENDAR_EXCHANGES

    def fetch(self, mode: str = "update") -> int:
        start = int_to_date(self.ctx.start_date or CALENDAR_INIT_START)
        # 多取一年缓冲，供 ingest 推导区间尾部的 next_trading_day
        today = int_to_date(today_int())
        next_year = today.year + 1
        end = today.replace(
            year=next_year, day=min(today.day, calendar.monthrange(next_year, today.month)[1])
        )
        n = 0
        for exchange in self._exchanges():
            df = retry_call(
                self.client.query_all,
                self.API_NAME,
                max_retries=self.ctx.max_retries,
                backoff_base=self.ctx.backoff_base,
                logger=self.log,
                exchange=exchange,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                fields=TRADE_CAL_FIELDS,
            )
            if df is None or df.empty:
                if self.DATASET == "future_calendar":
                    raise ValueError(f"Missing future trading calendar: {exchange}")
                self.log.warning("calendar[%s] 无数据，跳过写入", exchange)
                sleep_s(self.ctx.sleep_between_requests)
                continue
            read_open_days(df, exchange)
            out = self.paths.dataset_file(self.PROVIDER, self.DATASET, exchange)
            write_parquet(df, out, append=False)
            self.log.info("calendar[%s] 写入 %d 行", exchange, len(df))
            n += 1
            sleep_s(self.ctx.sleep_between_requests)
        return n

    def _exchanges(self) -> tuple[str, ...]:
        return self.EXCHANGES


class FutureCalendarFetcher(CalendarFetcher):
    """期货交易日历独立落 raw，不用沪深日历代替各期货交易所。

    只取 ``providers.tushare.future_exchanges`` 白名单内的交易所；默认六所全取。
    """

    DATASET = "future_calendar"
    API_NAME = "fut_trade_cal"

    def __init__(self, client: object, ctx: RawContext) -> None:
        super().__init__(client, ctx)
        self.ctx = as_tushare_context(ctx)

    def _exchanges(self) -> tuple[str, ...]:
        return self.ctx.future_exchanges
