"""银河 ingest 层：/opt/raw_parquet/yinhe/ → PostgreSQL。"""

from gr_data.ingest.yinhe.importers import GROUPS, REGISTRY


__all__ = ["REGISTRY", "GROUPS"]
