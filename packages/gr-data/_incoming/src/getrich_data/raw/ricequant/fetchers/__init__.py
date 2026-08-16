"""米筐 raw fetcher 注册表。"""

from getrich_data.raw.ricequant.fetchers.bars import (
    Bars1dFetcher,
    CalendarFetcher,
    InstrumentsFetcher,
)

REGISTRY = {
    "instruments": InstrumentsFetcher,
    "calendar": CalendarFetcher,
    "bars_1d": Bars1dFetcher,
}

__all__ = ["REGISTRY", "InstrumentsFetcher", "CalendarFetcher", "Bars1dFetcher"]
