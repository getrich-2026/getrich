"""Tushare ingest 层：$RAW_PARQUET_ROOT/tushare/ → PostgreSQL。"""

from gr_data.ingest.tushare.importers import GROUPS, REGISTRY


__all__ = ["REGISTRY", "GROUPS"]
