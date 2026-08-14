"""Canonical Polars factor schema validation.

Defines expected columns and validation for ``factors_long`` tables
that store pre-computed factor values in long format
(``dt``, ``symbol``, ``factor``, ``value``).
"""

from __future__ import annotations

import polars as pl

from getrich_backtest.exceptions import BarSchemaError


# ---------------------------------------------------------------------------
# Column constants
# ---------------------------------------------------------------------------

FACTOR_REQUIRED_COLUMNS: frozenset[str] = frozenset(
    {
        "dt",  # Datetime("ms", "Asia/Shanghai") — bar datetime
        "symbol",  # Utf8 — instrument identifier
        "factor",  # Utf8 — factor name (e.g. "mom20", "rs_14")
        "value",  # Float64 — pre-computed factor value
    }
)

FACTOR_OPTIONAL_COLUMNS: frozenset[str] = frozenset(
    {
        "asset_class",  # Utf8 — optional asset class filter
    }
)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_factor_schema(df: pl.DataFrame) -> pl.DataFrame:
    """Validate and return factor DataFrame, sorted by ``factor`` then ``dt``.

    Checks that all required columns are present.
    """
    if not isinstance(df, pl.DataFrame):
        raise BarSchemaError("factor data must be a polars.DataFrame")

    if df.is_empty():
        return df

    missing: list[str] = sorted(FACTOR_REQUIRED_COLUMNS.difference(df.columns))
    if missing:
        raise BarSchemaError(f"factor data missing required columns: {', '.join(missing)}")

    return df.sort(["factor", "dt", "symbol"])


__all__ = [
    "FACTOR_OPTIONAL_COLUMNS",
    "FACTOR_REQUIRED_COLUMNS",
    "validate_factor_schema",
]
