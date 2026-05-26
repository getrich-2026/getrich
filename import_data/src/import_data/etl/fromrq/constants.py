# RiceQuant Instrument Types
INSTRUMENT_TYPES = [
    "CS",  # Common Stock
    "ETF",  # Exchange Traded Fund
    "LOF",  # Listed Open-Ended Fund
    "INDX",  # Index
    "Future",  # Futures
    "Spot",  # Spot
    "Option",  # Option
    "Convertible",  # Convertible Bond
    "Repo",  # Repo
]

# Chinese to English mapping for RiceQuant data folders (aligned with INSTRUMENT_TYPES)
FOLDER_NAME_MAP = {
    "ETF": "ETF",
    "股票": "CS",
    "回购": "Repo",
    "可转债": "Convertible",
    "可转债衍生指标": "ConvertibleExtra",
    "期货": "Future",
    "期权": "Option",
    "指数": "INDX",
}
