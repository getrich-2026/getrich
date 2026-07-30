"""Tushare raw 层：Tushare Pro → /opt/raw_parquet/tushare/。"""

from getrich_data.raw.tushare.client import TushareClient, TushareProClient
from getrich_data.raw.tushare.fetchers import REGISTRY

__all__ = ["TushareClient", "TushareProClient", "REGISTRY"]
