"""Tests for factor schema validation."""

from datetime import datetime

import polars as pl
import pytest
from gr_backtest import get_shanghai_tz
from gr_backtest.data.factor_schema import (
    FACTOR_OPTIONAL_COLUMNS,
    FACTOR_REQUIRED_COLUMNS,
    validate_factor_schema,
)
from gr_backtest.exceptions import BarSchemaError


TZ = get_shanghai_tz()


class TestValidateFactorSchema:
    def test_valid_factor_data(self) -> None:
        df = pl.DataFrame(
            {
                "dt": [datetime(2026, 1, 15, 9, 30, tzinfo=TZ)],
                "symbol": ["000001.SZ"],
                "factor": ["mom20"],
                "value": [0.05],
            },
            schema={
                "dt": pl.Datetime("ms", "Asia/Shanghai"),
                "symbol": pl.Utf8,
                "factor": pl.Utf8,
                "value": pl.Float64,
            },
        )
        result = validate_factor_schema(df)
        assert result.height == 1

    def test_missing_required_column(self) -> None:
        df = pl.DataFrame(
            {"dt": [datetime(2026, 1, 15, 9, 30, tzinfo=TZ)], "symbol": ["000001.SZ"]},
            schema={"dt": pl.Datetime("ms", "Asia/Shanghai"), "symbol": pl.Utf8},
        )
        with pytest.raises(BarSchemaError, match="missing required"):
            validate_factor_schema(df)

    def test_empty_dataframe(self) -> None:
        df = pl.DataFrame(
            {col: [] for col in ("dt", "symbol", "factor", "value")},
            schema={
                "dt": pl.Datetime("ms", "Asia/Shanghai"),
                "symbol": pl.Utf8,
                "factor": pl.Utf8,
                "value": pl.Float64,
            },
        )
        result = validate_factor_schema(df)
        assert result.is_empty()

    def test_sorts_by_factor_dt_symbol(self) -> None:
        df = pl.DataFrame(
            {
                "dt": [
                    datetime(2026, 1, 15, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 10, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 15, 9, 30, tzinfo=TZ),
                ],
                "symbol": ["B", "A", "A"],
                "factor": ["z_factor", "mom20", "mom20"],
                "value": [0.1, 0.05, 0.03],
            },
            schema={
                "dt": pl.Datetime("ms", "Asia/Shanghai"),
                "symbol": pl.Utf8,
                "factor": pl.Utf8,
                "value": pl.Float64,
            },
        )
        result = validate_factor_schema(df)
        rows = result.rows()
        # Sorted by factor first, then dt, then symbol
        assert rows[0][2] == "mom20"  # factor
        assert rows[1][2] == "mom20"
        assert rows[2][2] == "z_factor"

    def test_optional_columns_accepted(self) -> None:
        df = pl.DataFrame(
            {
                "dt": [datetime(2026, 1, 15, 9, 30, tzinfo=TZ)],
                "symbol": ["000001.SZ"],
                "factor": ["mom20"],
                "value": [0.05],
                "asset_class": ["equity"],
            },
            schema={
                "dt": pl.Datetime("ms", "Asia/Shanghai"),
                "symbol": pl.Utf8,
                "factor": pl.Utf8,
                "value": pl.Float64,
                "asset_class": pl.Utf8,
            },
        )
        result = validate_factor_schema(df)
        assert result.height == 1
        assert "asset_class" in result.columns

    def test_not_polars_input(self) -> None:
        with pytest.raises(BarSchemaError, match="must be a polars"):
            validate_factor_schema("not a dataframe")  # type: ignore[arg-type]

    def test_required_columns_constant(self) -> None:
        assert "dt" in FACTOR_REQUIRED_COLUMNS
        assert "symbol" in FACTOR_REQUIRED_COLUMNS
        assert "factor" in FACTOR_REQUIRED_COLUMNS
        assert "value" in FACTOR_REQUIRED_COLUMNS

    def test_optional_columns_constant(self) -> None:
        assert "asset_class" in FACTOR_OPTIONAL_COLUMNS
