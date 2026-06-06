"""Public types and enums used by the backtesting framework."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum


class AssetClass(str, Enum):
    """Supported asset classes."""

    EQUITY_A = "equity_a"
    EQUITY_OPTION_A = "equity_option_a"
    COMMODITY_FUTURE = "commodity_future"
    INDEX_FUTURE = "index_future"
    COMMODITY_FUTURE_OPTION = "commodity_future_option"
    INDEX_FUTURE_OPTION = "index_future_option"


class Exchange(str, Enum):
    """Supported exchanges."""

    SSE = "SSE"
    SZSE = "SZSE"
    BSE = "BSE"
    CFFEX = "CFFEX"
    SHFE = "SHFE"
    DCE = "DCE"
    CZCE = "CZCE"
    INE = "INE"
    GFEX = "GFEX"


class Frequency(str, Enum):
    """Canonical bar frequencies."""

    ONE_MIN = "1m"
    FIVE_MIN = "5m"
    FIFTEEN_MIN = "15m"
    THIRTY_MIN = "30m"
    SIXTY_MIN = "60m"
    ONE_HOUR = "1h"
    ONE_DAY = "1d"

    @classmethod
    def is_valid(cls, freq: str) -> bool:
        """Return ``True`` if *freq* is a known frequency value."""
        return freq in cls._value2member_map_

    @classmethod
    def all_values(cls) -> frozenset[str]:
        """Return all canonical frequency strings."""
        return frozenset(cls._value2member_map_.keys())


class Side(str, Enum):
    """Strategy-facing order sides."""

    BUY = "BUY"
    SELL = "SELL"
    OPEN_LONG = "OPEN_LONG"
    OPEN_SHORT = "OPEN_SHORT"
    CLOSE_LONG = "CLOSE_LONG"
    CLOSE_SHORT = "CLOSE_SHORT"


class OrderType(str, Enum):
    """Supported order intent types."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class TimeInForce(str, Enum):
    """Supported time-in-force policies."""

    DAY = "DAY"
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"
    AUCTION = "AUCTION"


# Map frequency strings to their duration in minutes (1 day = 1440 minutes).
# Used for frequency ordering / coarseness comparisons.
FREQ_TO_MINUTES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "60m": 60,
    "1h": 60,
    "1d": 1440,
}

Money = Decimal
Quantity = Decimal
Symbol = str
