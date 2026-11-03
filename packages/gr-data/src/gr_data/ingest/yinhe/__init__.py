"""银河 ingest 层：$RAW_PARQUET_ROOT/yinhe/ → PostgreSQL。"""

from gr_data.ingest.yinhe.importers import GROUPS, REGISTRY


__all__ = ["REGISTRY", "GROUPS"]
