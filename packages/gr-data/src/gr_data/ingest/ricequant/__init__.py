"""米筐 ingest 层：/opt/raw_parquet/ricequant/ → PostgreSQL。"""

from gr_data.ingest.ricequant.importers import GROUPS, REGISTRY


__all__ = ["REGISTRY", "GROUPS"]
