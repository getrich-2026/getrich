"""Canonical Polars adj-factor schema validation.

Defines expected columns and validation for ``md_adj_factor_equity`` tables
that store cumulative pre- and post-adjustment factors for corporate actions.
"""

from __future__ import annotations

import polars as pl

from gr_backtest.exceptions import BarSchemaError


# ---------------------------------------------------------------------------
# Column constants
# ---------------------------------------------------------------------------

ADJ_REQUIRED_COLUMNS: frozenset[str] = frozenset(
    {
        "symbol",  # Utf8 — instrument identifier
        "dt",  # Date — ex-date of the corporate action
        "pre_factor",  # Float64 — cumulative pre-adjustment factor
        "post_factor",  # Float64 — cumulative post-adjustment factor
    }
)

ADJ_OPTIONAL_COLUMNS: frozenset[str] = frozenset(
    {
        "event_type",  # Utf8 — {div, split, rights, bonus}
        "cash_dividend",  # Float64
        "split_ratio",  # Float64
        "rights_price",  # Float64
        "rights_ratio",  # Float64
    }
)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_adj_schema(df: pl.DataFrame) -> pl.DataFrame:
    """Validate and return adj-factor DataFrame sorted by ``symbol``, ``dt``.

    Checks that all required columns are present.
    """
    if not isinstance(df, pl.DataFrame):
        raise BarSchemaError("adj factor data must be a polars.DataFrame")

    if df.is_empty():
        return df

    missing: list[str] = sorted(ADJ_REQUIRED_COLUMNS.difference(df.columns))
    if missing:
        raise BarSchemaError(f"adj factor data missing required columns: {', '.join(missing)}")

    return df.sort(["symbol", "dt"])


__all__ = [
    "ADJ_OPTIONAL_COLUMNS",
    "ADJ_REQUIRED_COLUMNS",
    "validate_adj_schema",
]
