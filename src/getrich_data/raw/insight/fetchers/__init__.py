"""华泰 INSIGHT raw fetcher 注册表。"""

from getrich_data.raw.insight.fetchers.bars import (
    BasicInfoFetcher,
    KlineDayFetcher,
    TradingDaysFetcher,
)

REGISTRY = {
    "basic_info": BasicInfoFetcher,
    "trading_days": TradingDaysFetcher,
    "kline_day": KlineDayFetcher,
}

__all__ = ["REGISTRY", "BasicInfoFetcher", "TradingDaysFetcher", "KlineDayFetcher"]
