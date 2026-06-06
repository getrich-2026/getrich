"""Tests for adj-factor schema validation."""

from datetime import date

import polars as pl
import pytest

from getrich_backtest.data.adj_schema import (
    ADJ_OPTIONAL_COLUMNS,
    ADJ_REQUIRED_COLUMNS,
    validate_adj_schema,
)
from getrich_backtest.exceptions import BarSchemaError


class TestValidateAdjSchema:
    def test_valid_adj_data(self) -> None:
        df = pl.DataFrame(
            {
                "symbol": ["000001.SZ"],
                "dt": [date(2026, 6, 15)],
                "pre_factor": [0.95],
                "post_factor": [1.05],
            },
            schema={
                "symbol": pl.Utf8,
                "dt": pl.Date,
                "pre_factor": pl.Float64,
                "post_factor": pl.Float64,
            },
        )
        result = validate_adj_schema(df)
        assert result.height == 1

    def test_missing_required_column(self) -> None:
        df = pl.DataFrame(
            {"symbol": ["000001.SZ"], "dt": [date(2026, 6, 15)]},
            schema={"symbol": pl.Utf8, "dt": pl.Date},
        )
        with pytest.raises(BarSchemaError, match="missing required"):
            validate_adj_schema(df)

    def test_empty_dataframe(self) -> None:
        df = pl.DataFrame(
            {col: [] for col in ("symbol", "dt", "pre_factor", "post_factor")},
            schema={
                "symbol": pl.Utf8,
                "dt": pl.Date,
                "pre_factor": pl.Float64,
                "post_factor": pl.Float64,
            },
        )
        result = validate_adj_schema(df)
        assert result.is_empty()

    def test_sorts_by_symbol_dt(self) -> None:
        df = pl.DataFrame(
            {
                "symbol": ["B", "A", "A"],
                "dt": [date(2026, 6, 2), date(2026, 6, 3), date(2026, 6, 1)],
                "pre_factor": [0.95, 0.98, 0.99],
                "post_factor": [1.05, 1.02, 1.01],
            },
            schema={
                "symbol": pl.Utf8,
                "dt": pl.Date,
                "pre_factor": pl.Float64,
                "post_factor": pl.Float64,
            },
        )
        result = validate_adj_schema(df)
        rows = result.rows()
        # Sorted by symbol first, then dt
        assert rows[0][0] == "A" and rows[0][1] == date(2026, 6, 1)
        assert rows[1][0] == "A" and rows[1][1] == date(2026, 6, 3)
        assert rows[2][0] == "B" and rows[2][1] == date(2026, 6, 2)

    def test_not_polars_input(self) -> None:
        with pytest.raises(BarSchemaError, match="must be a polars"):
            validate_adj_schema("not a dataframe")  # type: ignore[arg-type]

    def test_required_columns_constant(self) -> None:
        assert "symbol" in ADJ_REQUIRED_COLUMNS
        assert "dt" in ADJ_REQUIRED_COLUMNS
        assert "pre_factor" in ADJ_REQUIRED_COLUMNS
        assert "post_factor" in ADJ_REQUIRED_COLUMNS

    def test_optional_columns_constant(self) -> None:
        assert "event_type" in ADJ_OPTIONAL_COLUMNS
