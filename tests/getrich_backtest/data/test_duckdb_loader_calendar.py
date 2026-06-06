"""Tests for DuckDBBarLoader.load_calendar() using real DuckDB in-memory."""

from datetime import date

import polars as pl

from getrich_backtest import DuckDBBarLoader, get_shanghai_tz


TZ = get_shanghai_tz()


def _make_calendar() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "date": [
                date(2026, 6, 1),
                date(2026, 6, 2),
                date(2026, 6, 3),
                date(2026, 6, 4),
            ],
            "is_trading_day": [True, True, False, True],
            "exchange": ["SSE", "SSE", "SSE", "SSE"],
        }
    )


class TestDuckDBBarLoaderCalendar:
    def test_load_calendar_basic(self) -> None:
        loader = DuckDBBarLoader()
        loader.register_df("md_calendar_SSE", _make_calendar())
        result = loader.load_calendar(exchange="SSE")
        assert result.height == 4
        assert "date" in result.columns
        assert "is_trading_day" in result.columns

    def test_load_calendar_empty_table(self) -> None:
        loader = DuckDBBarLoader()
        # Register empty table
        empty = pl.DataFrame(
            {"date": [], "is_trading_day": []},
            schema={"date": pl.Date, "is_trading_day": pl.Boolean},
        )
        loader.register_df("md_calendar_SSE", empty)
        result = loader.load_calendar(exchange="SSE")
        assert result.is_empty()

    def test_load_calendar_custom_exchange(self) -> None:
        loader = DuckDBBarLoader()
        # Register both exchanges
        cal = _make_calendar()
        loader.register_df("md_calendar_SSE", cal)
        shfe = cal.with_columns(pl.lit("SHFE").alias("exchange"))
        loader.register_df("md_calendar_SHFE", shfe)
        result = loader.load_calendar(exchange="SHFE")
        assert result.height == 4
