"""华泰 INSIGHT raw 层：insight_python → $RAW_PARQUET_ROOT/insight/。"""

from gr_data.raw.insight.client import InsightApiClient, InsightClient
from gr_data.raw.insight.fetchers import REGISTRY


__all__ = ["InsightApiClient", "InsightClient", "REGISTRY"]
