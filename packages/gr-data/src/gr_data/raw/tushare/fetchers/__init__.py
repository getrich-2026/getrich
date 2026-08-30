"""Tushare raw fetcher 注册表。"""

from gr_data.raw.tushare.fetchers.market import (
    AdjFactorFetcher,
    Bars1dFetcher,
    FutureBars1dFetcher,
    IndexBars1dFetcher,
    StockLimitFetcher,
    SuspensionFetcher,
)
from gr_data.raw.tushare.fetchers.reference import (
    CalendarFetcher,
    InstrumentsFetcher,
)


REGISTRY = {
    "instruments": InstrumentsFetcher,
    "calendar": CalendarFetcher,
    "daily": Bars1dFetcher,
    "adj_factor": AdjFactorFetcher,
    "stk_limit": StockLimitFetcher,
    "suspend_d": SuspensionFetcher,
    "index_daily": IndexBars1dFetcher,
    "fut_daily": FutureBars1dFetcher,
}

__all__ = ["REGISTRY"]
