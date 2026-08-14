"""Canonical Polars corporate actions schema validation.

Defines expected columns and validation for ``corp_actions`` tables
that describe cash dividends, stock splits, bonus issues, and rights
offerings.
"""

from __future__ import annotations

import polars as pl

from getrich_backtest.exceptions import BarSchemaError


# ---------------------------------------------------------------------------
# Column constants
# ---------------------------------------------------------------------------

CORP_ACTIONS_REQUIRED_COLUMNS: frozenset[str] = frozenset(
    {
        "symbol",  # instrument identifier
        "ex_date",  # ex-date when the action takes effect (Date)
        "action_type",  # one of: "dividend", "split", "bonus", "rights"
    }
)

CORP_ACTIONS_OPTIONAL_COLUMNS: frozenset[str] = frozenset(
    {
        "announce_date",  # Date — announcement date
        "amount",  # Float64 — cash dividend per share
        "split_ratio",  # Float64 — e.g. 2 for a 2:1 split
        "bonus_ratio",  # Float64 — e.g. 0.5 → 1 bonus share per 2 held
        "rights_price",  # Float64 — rights issue subscription price
        "rights_ratio",  # Float64 — rights issue ratio
        "currency",  # Utf8 — dividend currency
        "note",  # Utf8 — free-form remarks
    }
)

# Valid action_type values
VALID_ACTION_TYPES: frozenset[str] = frozenset({"dividend", "split", "bonus", "rights"})


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_corp_actions_schema(df: pl.DataFrame) -> pl.DataFrame:
    """Validate and return corporate-actions DataFrame, sorted by
    ``ex_date`` then ``symbol``.

    Checks that all required columns are present and that ``action_type``
    values are recognised.
    """
    if not isinstance(df, pl.DataFrame):
        raise BarSchemaError("corp_actions data must be a polars.DataFrame")

    if df.is_empty():
        return df

    missing: list[str] = sorted(CORP_ACTIONS_REQUIRED_COLUMNS.difference(df.columns))
    if missing:
        raise BarSchemaError(f"corp_actions missing required columns: {', '.join(missing)}")

    # Validate that action_type contains only recognised values (if present)
    if "action_type" in df.columns:
        actual = set(df["action_type"].unique().to_list())
        unknown = actual.difference(VALID_ACTION_TYPES)
        if unknown:
            raise BarSchemaError(
                f"corp_actions contains unknown action_type values: {', '.join(sorted(unknown))}"
            )

    return df.sort(["ex_date", "symbol"])


__all__ = [
    "CORP_ACTIONS_OPTIONAL_COLUMNS",
    "CORP_ACTIONS_REQUIRED_COLUMNS",
    "VALID_ACTION_TYPES",
    "validate_corp_actions_schema",
]
