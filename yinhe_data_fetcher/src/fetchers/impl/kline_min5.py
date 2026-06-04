"""5 分钟 K 线."""

from __future__ import annotations

from ..base import KlineFetcher


class KlineMin5Fetcher(KlineFetcher):
    NAME = "kline_min5"
    PERIOD = "min5"
    SECURITY_TYPES = ["EXTRA_STOCK_A_SH_SZ"]
    INIT_START_DATE = 20130101
    CODE_CHUNK_SIZE = 10
    DATE_CHUNK_DAYS = 20
