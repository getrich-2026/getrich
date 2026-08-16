"""Tushare ingest importer 注册表。"""

from getrich_data.ingest.tushare.importers.bars import (
    FutureBars1dImporter,
    IndexBars1dImporter,
    StockBars1dImporter,
)
from getrich_data.ingest.tushare.importers.reference import (
    CalendarImporter,
    InstrumentsImporter,
    SymbolMapImporter,
)

REGISTRY = {
    "instruments": InstrumentsImporter,
    "symbol_map": SymbolMapImporter,
    "calendar": CalendarImporter,
    "stock_bar_1d": StockBars1dImporter,
    "index_bar_1d": IndexBars1dImporter,
    "future_bar_1d": FutureBars1dImporter,
}

# 组别快捷方式。注意 instruments → symbol_map → bars 有严格先后依赖：
# bars 需要 symbol_map 解析 instrument_id。
GROUPS = {
    "reference": ["instruments", "symbol_map", "calendar"],
    "bars_1d": ["stock_bar_1d", "index_bar_1d", "future_bar_1d"],
    "all": [
        "instruments",
        "symbol_map",
        "calendar",
        "stock_bar_1d",
        "index_bar_1d",
        "future_bar_1d",
    ],
}

__all__ = ["REGISTRY", "GROUPS"]
