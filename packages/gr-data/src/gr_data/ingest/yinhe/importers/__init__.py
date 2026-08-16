"""银河 ingest importer 注册表。键即 config enabled.ingest.yinhe 项。

执行顺序由 list 顺序保证：instruments → symbol_map → calendar → bars。
"""

from gr_data.ingest.yinhe.importers.bars import (
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

# bars_1d 作为一组别名，展开为三个 asset importer
GROUPS = {"bars_1d": ["stock_bar_1d", "etf_bar_1d", "index_bar_1d"]}

__all__ = ["REGISTRY", "GROUPS"]
