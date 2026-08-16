"""华泰 INSIGHT ingest 层：/opt/raw_parquet/insight/ → PostgreSQL。"""

from getrich_data.ingest.insight.importers import GROUPS, REGISTRY

__all__ = ["REGISTRY", "GROUPS"]
