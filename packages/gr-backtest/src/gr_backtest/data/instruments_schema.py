"""Canonical Polars instruments schema validation.

Defines expected columns and validation for ``instruments_equity``,
``instruments_future``, and ``instruments_option`` metadata tables.
"""

from __future__ import annotations

import polars as pl

from gr_backtest.exceptions import BarSchemaError


# ---------------------------------------------------------------------------
# Column constants — per asset class
# ---------------------------------------------------------------------------

INSTRUMENTS_EQUITY_COLUMNS: frozenset[str] = frozenset(
    {
        "symbol",
        "name",
        "exchange",
        "list_date",
        "delist_date",
        "lot_size",
        "industry_l1",
        "industry_l2",
        "industry_l3",
    }
)

INSTRUMENTS_FUTURE_COLUMNS: frozenset[str] = frozenset(
    {
        "symbol",
        "product",
        "exchange",
        "multiplier",
        "tick_size",
        "tick_value",
        "margin_ratio_long",
        "margin_ratio_short",
        "list_date",
        "last_trade_date",
        "delivery_date",
        "night_session",
    }
)

INSTRUMENTS_OPTION_COLUMNS: frozenset[str] = frozenset(
    {
        "symbol",
        "underlying",
        "strike",
        "expiry",
        "option_type",
        "exercise_style",
        "multiplier",
        "tick_size",
        "list_date",
    }
)

# Mapping from asset_class string to its required column set
INSTRUMENTS_COLUMNS_BY_CLASS: dict[str, frozenset[str]] = {
    "equity_a": INSTRUMENTS_EQUITY_COLUMNS,
    "equity_a_option": INSTRUMENTS_OPTION_COLUMNS,
    "commodity_future": INSTRUMENTS_FUTURE_COLUMNS,
    "index_future": INSTRUMENTS_FUTURE_COLUMNS,
}

# Core subset expected by all instrument types
INSTRUMENTS_BASE_COLUMNS: frozenset[str] = frozenset({"symbol"})


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_instruments_schema(df: pl.DataFrame, asset_class: str) -> pl.DataFrame:
    """Validate and return instruments DataFrame sorted by ``symbol``.

    Checks that all required columns for the given asset class are present.
    Unknown or unreachable asset classes are accepted with just the base
    ``symbol`` requirement.
    """
    if not isinstance(df, pl.DataFrame):
        raise BarSchemaError("instruments data must be a polars.DataFrame")

    if df.is_empty():
        return df

    # Determine the expected column set for this asset class
    expected = INSTRUMENTS_COLUMNS_BY_CLASS.get(asset_class, INSTRUMENTS_BASE_COLUMNS)
    missing = sorted(expected.difference(df.columns))
    if missing:
        raise BarSchemaError(
            f"instruments ({asset_class}) missing required columns: {', '.join(missing)}"
        )

    return df.sort("symbol")


__all__ = [
    "INSTRUMENTS_BASE_COLUMNS",
    "INSTRUMENTS_COLUMNS_BY_CLASS",
    "INSTRUMENTS_EQUITY_COLUMNS",
    "INSTRUMENTS_FUTURE_COLUMNS",
    "INSTRUMENTS_OPTION_COLUMNS",
    "validate_instruments_schema",
]
