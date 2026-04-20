"""日线 K 线."""

from __future__ import annotations

from ..base import KlineFetcher


class KlineDayFetcher(KlineFetcher):
    NAME = "kline_day"
    PERIOD = "day"
    SECURITY_TYPES = [
        "EXTRA_STOCK_A_SH_SZ",
        "EXTRA_ETF",
        "EXTRA_IDNEX_A_SH_SZ",
    ]
    INIT_START_DATE = 20130101
    CODE_CHUNK_SIZE = 30
    DATE_CHUNK_DAYS = 120
