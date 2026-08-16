"""华泰 INSIGHT ingest importer 注册表。"""

from getrich_data.ingest.insight.importers.bars import (
    CalendarImporter,
    EtfBars1dImporter,
    IndexBars1dImporter,
    InstrumentsImporter,
    StockBars1dImporter,
    SymbolMapImporter,
)

REGISTRY = {
    "instruments": InstrumentsImporter,
    "symbol_map": SymbolMapImporter,
    "calendar": CalendarImporter,
    "stock_bar_1d": StockBars1dImporter,
    "etf_bar_1d": EtfBars1dImporter,
    "index_bar_1d": IndexBars1dImporter,
}
GROUPS = {"bars_1d": ["stock_bar_1d", "etf_bar_1d", "index_bar_1d"]}

__all__ = ["REGISTRY", "GROUPS"]
