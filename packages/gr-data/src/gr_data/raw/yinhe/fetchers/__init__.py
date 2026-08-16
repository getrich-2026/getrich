"""银河 raw fetcher 注册表。"""

from gr_data.raw.yinhe.fetchers.kline import KlineDayFetcher, KlineMin1Fetcher
from gr_data.raw.yinhe.fetchers.reference import (
    BackwardFactorFetcher,
    CalendarFetcher,
    HistCodeListFetcher,
)


# name -> fetcher class（name 即 config enabled.raw.yinhe 列表中的项）
REGISTRY = {
    "calendar": CalendarFetcher,
    "hist_code_list": HistCodeListFetcher,
    "backward_factor": BackwardFactorFetcher,
    "kline_day": KlineDayFetcher,
    "kline_min1": KlineMin1Fetcher,
}

__all__ = [
    "REGISTRY",
    "CalendarFetcher",
    "HistCodeListFetcher",
    "BackwardFactorFetcher",
    "KlineDayFetcher",
    "KlineMin1Fetcher",
]
