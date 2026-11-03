"""华泰 INSIGHT ingest 层：$RAW_PARQUET_ROOT/insight/ → PostgreSQL。"""

from gr_data.ingest.insight.importers import GROUPS, REGISTRY


__all__ = ["REGISTRY", "GROUPS"]
