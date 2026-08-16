"""Data loading and validation utilities."""

from gr_backtest.data.adj_schema import (
    ADJ_OPTIONAL_COLUMNS,
    ADJ_REQUIRED_COLUMNS,
    validate_adj_schema,
)
from gr_backtest.data.calendar_schema import (
    CALENDAR_OPTIONAL_COLUMNS,
    CALENDAR_REQUIRED_COLUMNS,
    validate_calendar_schema,
)
from gr_backtest.data.corp_actions_schema import (
    CORP_ACTIONS_OPTIONAL_COLUMNS,
    CORP_ACTIONS_REQUIRED_COLUMNS,
    VALID_ACTION_TYPES,
    validate_corp_actions_schema,
)
from gr_backtest.data.duckdb_loader import DuckDBBarLoader
from gr_backtest.data.factor_schema import (
    FACTOR_OPTIONAL_COLUMNS,
    FACTOR_REQUIRED_COLUMNS,
    validate_factor_schema,
)
from gr_backtest.data.instruments_schema import (
    INSTRUMENTS_BASE_COLUMNS,
    INSTRUMENTS_COLUMNS_BY_CLASS,
    INSTRUMENTS_EQUITY_COLUMNS,
    INSTRUMENTS_FUTURE_COLUMNS,
    INSTRUMENTS_OPTION_COLUMNS,
    validate_instruments_schema,
)
from gr_backtest.data.loader import BarLoader, DataFrameBarLoader
from gr_backtest.data.pg_loader import PgBarLoader
from gr_backtest.data.resample import resample_bars
from gr_backtest.data.schema import (
    BAR_OPTIONAL_COLUMNS,
    BAR_REQUIRED_COLUMNS,
    validate_bar_schema,
)


__all__ = [
    "ADJ_OPTIONAL_COLUMNS",
    "ADJ_REQUIRED_COLUMNS",
    "BAR_OPTIONAL_COLUMNS",
    "BAR_REQUIRED_COLUMNS",
    "BarLoader",
    "CALENDAR_OPTIONAL_COLUMNS",
    "CALENDAR_REQUIRED_COLUMNS",
    "CORP_ACTIONS_OPTIONAL_COLUMNS",
    "CORP_ACTIONS_REQUIRED_COLUMNS",
    "DataFrameBarLoader",
    "DuckDBBarLoader",
    "FACTOR_OPTIONAL_COLUMNS",
    "FACTOR_REQUIRED_COLUMNS",
    "INSTRUMENTS_BASE_COLUMNS",
    "INSTRUMENTS_COLUMNS_BY_CLASS",
    "INSTRUMENTS_EQUITY_COLUMNS",
    "INSTRUMENTS_FUTURE_COLUMNS",
    "INSTRUMENTS_OPTION_COLUMNS",
    "PgBarLoader",
    "resample_bars",
    "VALID_ACTION_TYPES",
    "validate_adj_schema",
    "validate_bar_schema",
    "validate_calendar_schema",
    "validate_corp_actions_schema",
    "validate_factor_schema",
    "validate_instruments_schema",
]
