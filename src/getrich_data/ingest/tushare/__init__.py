"""Tushare ingest 层：/opt/raw_parquet/tushare/ → PostgreSQL。"""

from getrich_data.ingest.tushare.importers import GROUPS, REGISTRY

__all__ = ["REGISTRY", "GROUPS"]
