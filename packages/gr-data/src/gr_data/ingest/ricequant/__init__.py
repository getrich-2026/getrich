"""米筐 ingest 层：$RAW_PARQUET_ROOT/ricequant/ → PostgreSQL。"""

from gr_data.ingest.ricequant.importers import GROUPS, REGISTRY


__all__ = ["REGISTRY", "GROUPS"]
