"""Tests for calendar schema validation."""

from datetime import date

import polars as pl
import pytest
from gr_backtest.data.calendar_schema import (
    validate_calendar_schema,
)
from gr_backtest.exceptions import BarSchemaError


class TestValidateCalendarSchema:
    def test_valid_calendar(self) -> None:
        df = pl.DataFrame(
            {"date": [date(2026, 6, 1)], "is_trading_day": [True]},
            schema={"date": pl.Date, "is_trading_day": pl.Boolean},
        )
        result = validate_calendar_schema(df)
        assert result.height == 1

    def test_missing_required_column(self) -> None:
        df = pl.DataFrame(
            {"date": [date(2026, 6, 1)]},
            schema={"date": pl.Date},
        )
        with pytest.raises(BarSchemaError, match="missing required"):
            validate_calendar_schema(df)

    def test_empty_dataframe(self) -> None:
        df = pl.DataFrame(
            {"date": [], "is_trading_day": []},
            schema={"date": pl.Date, "is_trading_day": pl.Boolean},
        )
        result = validate_calendar_schema(df)
        assert result.is_empty()

    def test_sorts_by_date(self) -> None:
        df = pl.DataFrame(
            {
                "date": [date(2026, 6, 3), date(2026, 6, 1), date(2026, 6, 2)],
                "is_trading_day": [True, True, False],
            },
            schema={"date": pl.Date, "is_trading_day": pl.Boolean},
        )
        result = validate_calendar_schema(df)
        dates = result["date"].to_list()
        assert dates == sorted(dates)

    def test_not_polars_input(self) -> None:
        with pytest.raises(BarSchemaError, match="must be a polars"):
            validate_calendar_schema("not a dataframe")  # type: ignore[arg-type]
