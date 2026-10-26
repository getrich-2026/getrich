"""Tushare raw fetcher 注册表。"""

from gr_data.raw.tushare.fetchers.asset_markets import (
    EtfInstrumentsFetcher,
    FundAdjFetcher,
    FundDailyFetcher,
    OptionCalendarFetcher,
    OptionDailyFetcher,
    OptionInstrumentsFetcher,
)
from gr_data.raw.tushare.fetchers.market import (
    AdjFactorFetcher,
    Bars1dFetcher,
    DailyBasicFetcher,
    FutureBars1dFetcher,
    IndexBars1dFetcher,
    StockLimitFetcher,
    SuspensionFetcher,
)
from gr_data.raw.tushare.fetchers.reference import (
    CalendarFetcher,
    FutureCalendarFetcher,
    InstrumentsFetcher,
)


REGISTRY = {
    "instruments": InstrumentsFetcher,
    "calendar": CalendarFetcher,
    "future_calendar": FutureCalendarFetcher,
    "daily": Bars1dFetcher,
    "adj_factor": AdjFactorFetcher,
    "daily_basic": DailyBasicFetcher,
    "stk_limit": StockLimitFetcher,
    "suspend_d": SuspensionFetcher,
    "index_daily": IndexBars1dFetcher,
    "fut_daily": FutureBars1dFetcher,
}

# 保留扩展前默认集合，新资产必须显式启用。
DEFAULT_DATASETS = tuple(REGISTRY)
REGISTRY.update(
    {
        "etf_instruments": EtfInstrumentsFetcher,
        "option_calendar": OptionCalendarFetcher,
        "fund_daily": FundDailyFetcher,
        "fund_adj": FundAdjFetcher,
        "opt_daily": OptionDailyFetcher,
        "option_instruments": OptionInstrumentsFetcher,
    }
)

__all__ = ["REGISTRY"]
