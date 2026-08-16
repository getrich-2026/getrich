"""Tests for DuckDBBarLoader.load_factors() using real DuckDB in-memory."""

from datetime import datetime

import polars as pl
from gr_backtest import DuckDBBarLoader, get_shanghai_tz


TZ = get_shanghai_tz()


def _make_factors() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "dt": [
                datetime(2026, 1, 15, 9, 30, tzinfo=TZ),
                datetime(2026, 1, 15, 9, 30, tzinfo=TZ),
                datetime(2026, 1, 16, 9, 30, tzinfo=TZ),
                datetime(2026, 1, 16, 9, 30, tzinfo=TZ),
            ],
            "symbol": ["000001.SZ", "000002.SZ", "000001.SZ", "000002.SZ"],
            "factor": ["mom20", "mom20", "rs_14", "rs_14"],
            "value": [0.05, -0.02, 0.8, 0.6],
        },
        schema={
            "dt": pl.Datetime("ms", "Asia/Shanghai"),
            "symbol": pl.Utf8,
            "factor": pl.Utf8,
            "value": pl.Float64,
        },
    )


class TestDuckDBBarLoaderFactors:
    def test_load_factors_basic(self) -> None:
        loader = DuckDBBarLoader()
        loader.register_df("factors_long", _make_factors())
        result = loader.load_factors()
        assert result.height == 4
        assert "dt" in result.columns
        assert "symbol" in result.columns
        assert "factor" in result.columns
        assert "value" in result.columns

    def test_load_factors_empty_table(self) -> None:
        loader = DuckDBBarLoader()
        empty = pl.DataFrame(
            {col: [] for col in ("dt", "symbol", "factor", "value")},
            schema={
                "dt": pl.Datetime("ms", "Asia/Shanghai"),
                "symbol": pl.Utf8,
                "factor": pl.Utf8,
                "value": pl.Float64,
            },
        )
        loader.register_df("factors_long", empty)
        result = loader.load_factors()
        assert result.is_empty()

    def test_load_factors_filter_by_factor(self) -> None:
        loader = DuckDBBarLoader()
        loader.register_df("factors_long", _make_factors())
        result = loader.load_factors(factors=["mom20"])
        assert result.height == 2
        factors = result["factor"].unique().to_list()
        assert factors == ["mom20"]
