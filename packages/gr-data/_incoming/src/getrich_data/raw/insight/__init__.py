"""华泰 INSIGHT raw 层：insight_python → /opt/raw_parquet/insight/。"""

from getrich_data.raw.insight.client import InsightApiClient, InsightClient
from getrich_data.raw.insight.fetchers import REGISTRY

__all__ = ["InsightApiClient", "InsightClient", "REGISTRY"]
