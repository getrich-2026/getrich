"""Tests for DuckDBBarLoader.load_adj_factors() using real DuckDB in-memory."""

from datetime import date

import polars as pl

from getrich_backtest import DuckDBBarLoader


def _make_adj_factors() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000002.SZ"],
            "dt": [date(2026, 6, 15), date(2026, 7, 1)],
            "pre_factor": [0.95, 0.90],
            "post_factor": [1.05, 1.10],
        },
        schema={
            "symbol": pl.Utf8,
            "dt": pl.Date,
            "pre_factor": pl.Float64,
            "post_factor": pl.Float64,
        },
    )


class TestDuckDBBarLoaderAdjFactors:
    def test_load_adj_factors_basic(self) -> None:
        loader = DuckDBBarLoader()
        loader.register_df("md_adj_factor_equity", _make_adj_factors())
        result = loader.load_adj_factors()
        assert result.height == 2
        assert "symbol" in result.columns
        assert "dt" in result.columns
        assert "pre_factor" in result.columns
        assert "post_factor" in result.columns

    def test_load_adj_factors_empty(self) -> None:
        loader = DuckDBBarLoader()
        empty = pl.DataFrame(
            {col: [] for col in ("symbol", "dt", "pre_factor", "post_factor")},
            schema={
                "symbol": pl.Utf8,
                "dt": pl.Date,
                "pre_factor": pl.Float64,
                "post_factor": pl.Float64,
            },
        )
        loader.register_df("md_adj_factor_equity", empty)
        result = loader.load_adj_factors()
        assert result.is_empty()

    def test_load_adj_factors_filter_symbol(self) -> None:
        loader = DuckDBBarLoader()
        loader.register_df("md_adj_factor_equity", _make_adj_factors())
        result = loader.load_adj_factors(symbols=["000001.SZ"])
        assert result.height == 1
        assert result["symbol"].to_list() == ["000001.SZ"]
