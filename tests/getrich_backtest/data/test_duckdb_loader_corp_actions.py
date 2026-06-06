"""Tests for DuckDBBarLoader.load_corp_actions() using real DuckDB in-memory."""

from datetime import date, datetime

import polars as pl

from getrich_backtest import DuckDBBarLoader, get_shanghai_tz


TZ = get_shanghai_tz()


def _make_corp_actions() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000002.SZ", "000001.SZ"],
            "ex_date": [date(2026, 6, 15), date(2026, 7, 1), date(2026, 8, 1)],
            "action_type": ["dividend", "split", "dividend"],
            "amount": [0.5, None, 0.3],
            "split_ratio": [None, 2.0, None],
        },
        schema={
            "symbol": pl.Utf8,
            "ex_date": pl.Date,
            "action_type": pl.Utf8,
            "amount": pl.Float64,
            "split_ratio": pl.Float64,
        },
    )


class TestDuckDBBarLoaderCorpActions:
    def test_load_corp_actions_basic(self) -> None:
        loader = DuckDBBarLoader()
        loader.register_df("corp_actions", _make_corp_actions())
        result = loader.load_corp_actions()
        assert result.height == 3
        assert "symbol" in result.columns
        assert "ex_date" in result.columns
        assert "action_type" in result.columns

    def test_load_corp_actions_empty_table(self) -> None:
        loader = DuckDBBarLoader()
        empty = pl.DataFrame(
            {"symbol": [], "ex_date": [], "action_type": []},
            schema={"symbol": pl.Utf8, "ex_date": pl.Date, "action_type": pl.Utf8},
        )
        loader.register_df("corp_actions", empty)
        result = loader.load_corp_actions()
        assert result.is_empty()

    def test_load_corp_actions_symbol_filter(self) -> None:
        loader = DuckDBBarLoader()
        loader.register_df("corp_actions", _make_corp_actions())
        result = loader.load_corp_actions(symbols=["000001.SZ"])
        assert result.height == 2  # two dividend entries for 000001.SZ
        symbols = result["symbol"].to_list()
        assert all(s == "000001.SZ" for s in symbols)

    def test_load_corp_actions_date_range(self) -> None:
        loader = DuckDBBarLoader()
        loader.register_df("corp_actions", _make_corp_actions())
        result = loader.load_corp_actions(
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 7, 15, tzinfo=TZ),
        )
        assert result.height == 2  # June 15 and July 1

    def test_load_corp_actions_date_range_none(self) -> None:
        loader = DuckDBBarLoader()
        loader.register_df("corp_actions", _make_corp_actions())
        result = loader.load_corp_actions(
            start=datetime(2026, 9, 1, tzinfo=TZ),
            end=datetime(2026, 10, 1, tzinfo=TZ),
        )
        assert result.is_empty()
