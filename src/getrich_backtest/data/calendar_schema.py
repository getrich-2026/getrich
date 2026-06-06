"""Canonical Polars calendar schema validation.

Defines expected columns and validation for exchange calendar data
loaded via ``BarLoader.load_calendar()``.
"""

from __future__ import annotations

import polars as pl

from getrich_backtest.exceptions import BarSchemaError


# ---------------------------------------------------------------------------
# Column constants
# ---------------------------------------------------------------------------

CALENDAR_REQUIRED_COLUMNS: frozenset[str] = frozenset({"date", "is_trading_day"})

CALENDAR_OPTIONAL_COLUMNS: frozenset[str] = frozenset({"exchange", "session", "note"})


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_calendar_schema(df: pl.DataFrame) -> pl.DataFrame:
    """Validate and return calendar DataFrame sorted by ``date``.

    Required columns: ``date``, ``is_trading_day``.
    """
    if not isinstance(df, pl.DataFrame):
        raise BarSchemaError("calendar data must be a polars.DataFrame")

    if df.is_empty():
        return df

    missing = sorted(CALENDAR_REQUIRED_COLUMNS.difference(df.columns))
    if missing:
        raise BarSchemaError(f"calendar missing required columns: {', '.join(missing)}")

    return df.sort("date")


__all__ = [
    "CALENDAR_OPTIONAL_COLUMNS",
    "CALENDAR_REQUIRED_COLUMNS",
    "validate_calendar_schema",
]
