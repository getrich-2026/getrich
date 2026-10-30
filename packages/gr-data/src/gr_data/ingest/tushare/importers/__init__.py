"""Tushare ingest importer 注册表。"""

from gr_data.ingest.tushare.importers.asset_markets import (
    EtfBars1dImporter,
    EtfInstrumentsImporter,
    EtfProfileImporter,
    EtfSymbolMapImporter,
    OptionBars1dImporter,
    OptionContractsImporter,
    OptionInstrumentsImporter,
    OptionSymbolMapImporter,
)
from gr_data.ingest.tushare.importers.classify import InstrumentCategoryImporter
from gr_data.ingest.tushare.importers.market import (
    AdjFactorTsImporter,
    FutureBars1dImporter,
    IndexBars1dImporter,
    StockBars1dImporter,
    ValuationImporter,
)
from gr_data.ingest.tushare.importers.profile import (
    FutureProfileImporter,
    IndexProfileImporter,
    StockProfileImporter,
)
from gr_data.ingest.tushare.importers.reference import (
    CalendarImporter,
    InstrumentsImporter,
    SymbolMapImporter,
)
from gr_data.ingest.tushare.importers.suspensions import SuspensionImporter


REGISTRY = {
    "instruments": InstrumentsImporter,
    "symbol_map": SymbolMapImporter,
    "calendar": CalendarImporter,
    "stock_profile": StockProfileImporter,
    "index_profile": IndexProfileImporter,
    "future_profile": FutureProfileImporter,
    "suspend_d": SuspensionImporter,
    "stock_bar_1d": StockBars1dImporter,
    "index_bar_1d": IndexBars1dImporter,
    "future_bar_1d": FutureBars1dImporter,
    "adj_factor_ts": AdjFactorTsImporter,
    "valuation_1d": ValuationImporter,
}

REGISTRY.update(
    {
        "etf_instruments": EtfInstrumentsImporter,
        "etf_symbol_map": EtfSymbolMapImporter,
        "etf_profile": EtfProfileImporter,
        "option_instruments": OptionInstrumentsImporter,
        "option_symbol_map": OptionSymbolMapImporter,
        "option_contracts": OptionContractsImporter,
        "etf_bar_1d": EtfBars1dImporter,
        "option_bar_1d": OptionBars1dImporter,
        # 注册顺序即执行顺序：分类读 meta.etf_profile，必须排在 etf_profile 之后。
        "instrument_category": InstrumentCategoryImporter,
    }
)

# 新资产必须显式启用，默认集合不含 ETF／期权。
DEFAULT_DATASETS = tuple(name for name in REGISTRY if not name.startswith(("etf_", "option_")))

# 组别快捷方式。注意 instruments → symbol_map → bars 有严格先后依赖：
# bars 需要 symbol_map 解析 instrument_id。
GROUPS = {
    "reference": ["instruments", "symbol_map", "calendar"],
    # 主数据快照里的描述性字段；依赖 instruments 已登记身份
    "profile": ["stock_profile", "index_profile", "future_profile"],
    "events": ["suspend_d"],
    "bars_1d": ["stock_bar_1d", "index_bar_1d", "future_bar_1d"],
    # 参考行情：不进 canonical K 线表，但同样需要 symbol_map 解析 instrument_id
    "market_ext": ["adj_factor_ts"],
    # daily_basic 的唯一落点（估值、股本、换手）
    "fundamental": ["valuation_1d"],
    # 纯规则映射，输入是已入库的 meta.instruments，不读 raw parquet
    "classify": ["instrument_category"],
    "all": [
        "instruments",
        "symbol_map",
        "calendar",
        "stock_profile",
        "index_profile",
        "future_profile",
        "suspend_d",
        "stock_bar_1d",
        "index_bar_1d",
        "future_bar_1d",
        "adj_factor_ts",
        "valuation_1d",
        "instrument_category",
    ],
    "etf_reference": ["etf_instruments", "etf_symbol_map", "etf_profile"],
    "etf_bars_1d": ["etf_bar_1d"],
    "option_reference": ["option_instruments", "option_symbol_map", "option_contracts"],
    "option_bars_1d": ["option_bar_1d"],
}

__all__ = ["REGISTRY", "GROUPS"]
