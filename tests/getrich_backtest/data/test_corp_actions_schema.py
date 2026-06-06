"""Tests for corporate-actions schema validation."""

from datetime import date

import polars as pl
import pytest

from getrich_backtest.data.corp_actions_schema import (
    VALID_ACTION_TYPES,
    validate_corp_actions_schema,
)
from getrich_backtest.exceptions import BarSchemaError


class TestValidateCorpActionsSchema:
    def test_valid_dividend(self) -> None:
        df = pl.DataFrame(
            {
                "symbol": ["000001.SZ"],
                "ex_date": [date(2026, 6, 15)],
                "action_type": ["dividend"],
                "amount": [0.5],
            },
            schema={
                "symbol": pl.Utf8,
                "ex_date": pl.Date,
                "action_type": pl.Utf8,
                "amount": pl.Float64,
            },
        )
        result = validate_corp_actions_schema(df)
        assert result.height == 1

    def test_valid_split(self) -> None:
        df = pl.DataFrame(
            {
                "symbol": ["000001.SZ"],
                "ex_date": [date(2026, 7, 1)],
                "action_type": ["split"],
                "split_ratio": [2.0],
            },
            schema={
                "symbol": pl.Utf8,
                "ex_date": pl.Date,
                "action_type": pl.Utf8,
                "split_ratio": pl.Float64,
            },
        )
        result = validate_corp_actions_schema(df)
        assert result.height == 1

    def test_missing_required_column(self) -> None:
        df = pl.DataFrame(
            {"symbol": ["000001.SZ"], "ex_date": [date(2026, 6, 15)]},
            schema={"symbol": pl.Utf8, "ex_date": pl.Date},
        )
        with pytest.raises(BarSchemaError, match="missing required"):
            validate_corp_actions_schema(df)

    def test_invalid_action_type(self) -> None:
        df = pl.DataFrame(
            {
                "symbol": ["000001.SZ"],
                "ex_date": [date(2026, 6, 15)],
                "action_type": ["unknown_action"],
            },
            schema={
                "symbol": pl.Utf8,
                "ex_date": pl.Date,
                "action_type": pl.Utf8,
            },
        )
        with pytest.raises(BarSchemaError, match="unknown action_type"):
            validate_corp_actions_schema(df)

    def test_valid_action_types_constant(self) -> None:
        assert "dividend" in VALID_ACTION_TYPES
        assert "split" in VALID_ACTION_TYPES
        assert "bonus" in VALID_ACTION_TYPES
        assert "rights" in VALID_ACTION_TYPES

    def test_empty_dataframe(self) -> None:
        df = pl.DataFrame(
            {"symbol": [], "ex_date": [], "action_type": []},
            schema={"symbol": pl.Utf8, "ex_date": pl.Date, "action_type": pl.Utf8},
        )
        result = validate_corp_actions_schema(df)
        assert result.is_empty()

    def test_sorts_by_ex_date_and_symbol(self) -> None:
        df = pl.DataFrame(
            {
                "symbol": ["B", "A", "A"],
                "ex_date": [date(2026, 6, 2), date(2026, 6, 3), date(2026, 6, 1)],
                "action_type": ["dividend", "split", "dividend"],
            },
            schema={
                "symbol": pl.Utf8,
                "ex_date": pl.Date,
                "action_type": pl.Utf8,
            },
        )
        result = validate_corp_actions_schema(df)
        rows = result.rows()
        # Sorted by ex_date first, then symbol
        assert rows[0][1] == date(2026, 6, 1)  # A, ex_date=6-1
        assert rows[1][1] == date(2026, 6, 2)  # B, ex_date=6-2
        assert rows[2][1] == date(2026, 6, 3)  # A, ex_date=6-3

    def test_not_polars_input(self) -> None:
        with pytest.raises(BarSchemaError, match="must be a polars"):
            validate_corp_actions_schema("not a dataframe")  # type: ignore[arg-type]
