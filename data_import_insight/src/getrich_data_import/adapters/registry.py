from __future__ import annotations

from getrich_data_import.adapters.base import HistoryDataSource
from getrich_data_import.adapters.insight import InsightSource
from getrich_data_import.adapters.ricequant import RiceQuantSource
from getrich_data_import.adapters.yinhe_parquet import YinheParquetSource
from getrich_data_import.common.config import Settings


def get_history_source(name: str, settings: Settings) -> HistoryDataSource:
    normalized = name.lower().replace("-", "_")
    if normalized in {"yinhe", "yinhe_parquet"}:
        return YinheParquetSource(settings.yinhe.data_dir, provider="yinhe")
    if normalized == "insight":
        return InsightSource(settings.insight, provider="insight")
    if normalized == "ricequant":
        return RiceQuantSource(settings.ricequant, provider="ricequant")
    raise ValueError(f"unknown provider: {name}")


def provider_names() -> tuple[str, ...]:
    return ("yinhe", "insight", "ricequant")

