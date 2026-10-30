"""米筐 raw fetcher 注册表。"""

from gr_data.raw.ricequant.fetchers.bars import (
    Bars1dFetcher,
    CalendarFetcher,
    InstrumentsFetcher,
)
from gr_data.raw.ricequant.fetchers.contracts import FutureContractsFetcher


REGISTRY = {
    "instruments": InstrumentsFetcher,
    "calendar": CalendarFetcher,
    "bars_1d": Bars1dFetcher,
    "future_contracts": FutureContractsFetcher,
}

__all__ = [
    "REGISTRY",
    "InstrumentsFetcher",
    "CalendarFetcher",
    "Bars1dFetcher",
    "FutureContractsFetcher",
]
