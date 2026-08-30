"""Tushare ingest importer 注册表。"""

from gr_data.ingest.tushare.importers.classify import InstrumentCategoryImporter
from gr_data.ingest.tushare.importers.market import (
    AdjFactorTsImporter,
    DailyBasicImporter,
    FutureBars1dImporter,
    IndexBars1dImporter,
    StockBars1dImporter,
    ValuationImporter,
)
from gr_data.ingest.tushare.importers.reference import (
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
    "daily_basic": DailyBasicImporter,
    "adj_factor_ts": AdjFactorTsImporter,
    "valuation_1d": ValuationImporter,
    "instrument_category": InstrumentCategoryImporter,
}

# 组别快捷方式。注意 instruments → symbol_map → bars 有严格先后依赖：
# bars 需要 symbol_map 解析 instrument_id。
GROUPS = {
    "reference": ["instruments", "symbol_map", "calendar"],
    "bars_1d": ["stock_bar_1d", "index_bar_1d", "future_bar_1d"],
    # 参考行情：不进 canonical K 线表，但同样需要 symbol_map 解析 instrument_id
    "market_ext": ["daily_basic", "adj_factor_ts"],
    # 面向分析的规整形态，与 market_ext 读同一份 raw
    "fundamental": ["valuation_1d"],
    # 纯规则映射，输入是已入库的 meta.instruments，不读 raw parquet
    "classify": ["instrument_category"],
    "all": [
        "instruments",
        "symbol_map",
        "calendar",
        "stock_bar_1d",
        "index_bar_1d",
        "future_bar_1d",
        "daily_basic",
        "adj_factor_ts",
        "valuation_1d",
        "instrument_category",
    ],
}

__all__ = ["REGISTRY", "GROUPS"]
