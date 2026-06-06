"""Tests for DataFrameBarLoader.load_bars() with adj_policy."""

from datetime import date, datetime

import polars as pl
import pytest

from getrich_backtest import DataFrameBarLoader, get_shanghai_tz


TZ = get_shanghai_tz()


def _make_bars() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "dt": [
                datetime(2026, 6, 1, 9, 30, tzinfo=TZ),
                datetime(2026, 6, 2, 9, 30, tzinfo=TZ),
                datetime(2026, 6, 3, 9, 30, tzinfo=TZ),
            ],
            "symbol": ["000001.SZ", "000001.SZ", "000001.SZ"],
            "open": [100.0, 102.0, 101.0],
            "high": [101.0, 103.0, 102.0],
            "low": [99.0, 101.0, 100.0],
            "close": [100.5, 102.5, 90.0],  # June 3 has a dividend gap
            "volume": [1000.0, 1000.0, 1000.0],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


def _make_adj_factors() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "dt": [date(2026, 6, 3)],  # ex-date
            "pre_factor": [0.90],  # price * 0.9 → pre-adjusted
            "post_factor": [1.1111111111],
        },
        schema={
            "symbol": pl.Utf8,
            "dt": pl.Date,
            "pre_factor": pl.Float64,
            "post_factor": pl.Float64,
        },
    )


class TestLoadBarsAdjPolicy:
    def test_adj_none_returns_raw(self) -> None:
        """Default adj_policy="none" returns raw prices."""
        loader = DataFrameBarLoader(
            bars=_make_bars(),
            adj_factors_df=_make_adj_factors(),
        )
        result = loader.load_bars(
            symbols=["000001.SZ"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 4, tzinfo=TZ),
        )
        # June 3 close should be 90.0 (raw)
        jun3 = result.filter(pl.col("dt").dt.date() == date(2026, 6, 3))
        assert jun3["close"].to_list() == [90.0]

    def test_adj_pre_adjusts_historical_prices(self) -> None:
        """adj_policy="pre" multiplies historical prices by pre_factor."""
        loader = DataFrameBarLoader(
            bars=_make_bars(),
            adj_factors_df=_make_adj_factors(),
        )
        result = loader.load_bars(
            symbols=["000001.SZ"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 4, tzinfo=TZ),
            adj_policy="pre",
        )
        # June 1 close: 100.5 * 0.90 = 90.45
        jun1 = result.filter(pl.col("dt").dt.date() == date(2026, 6, 1))
        assert jun1["close"].to_list()[0] == pytest.approx(90.45, rel=1e-3)
        # June 3 close: 90.0 * 0.90 = 81.0
        jun3 = result.filter(pl.col("dt").dt.date() == date(2026, 6, 3))
        assert jun3["close"].to_list()[0] == pytest.approx(81.0, rel=1e-3)

    def test_adj_post_adjusts_future_prices(self) -> None:
        """adj_policy="post" multiplies prices by post_factor."""
        loader = DataFrameBarLoader(
            bars=_make_bars(),
            adj_factors_df=_make_adj_factors(),
        )
        result = loader.load_bars(
            symbols=["000001.SZ"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 4, tzinfo=TZ),
            adj_policy="post",
        )
        # June 1 close: 100.5 * 1.11111... = ~111.67
        jun1 = result.filter(pl.col("dt").dt.date() == date(2026, 6, 1))
        assert jun1["close"].to_list()[0] == pytest.approx(111.6666667, rel=1e-3)

    def test_adj_no_factors_returns_raw(self) -> None:
        """Without adj_factors_df, adj_policy falls back to raw prices."""
        loader = DataFrameBarLoader(bars=_make_bars())  # no adj_factors_df
        result = loader.load_bars(
            symbols=["000001.SZ"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 4, tzinfo=TZ),
            adj_policy="pre",
        )
        # All prices should be raw since no adj factors
        jun1 = result.filter(pl.col("dt").dt.date() == date(2026, 6, 1))
        assert jun1["close"].to_list()[0] == 100.5

    def test_adj_open_high_low_all_adjusted(self) -> None:
        """All OHLC columns are adjusted, not just close."""
        loader = DataFrameBarLoader(
            bars=_make_bars(),
            adj_factors_df=_make_adj_factors(),
        )
        result = loader.load_bars(
            symbols=["000001.SZ"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 4, tzinfo=TZ),
            adj_policy="pre",
        )
        jun1 = result.filter(pl.col("dt").dt.date() == date(2026, 6, 1))
        assert jun1["open"].to_list()[0] == pytest.approx(90.0, rel=1e-3)  # 100 * 0.90
        assert jun1["high"].to_list()[0] == pytest.approx(90.9, rel=1e-3)  # 101 * 0.90
        assert jun1["low"].to_list()[0] == pytest.approx(89.1, rel=1e-3)  # 99 * 0.90

    def test_adj_volume_not_adjusted(self) -> None:
        """Volume column is NOT affected by adj_policy."""
        loader = DataFrameBarLoader(
            bars=_make_bars(),
            adj_factors_df=_make_adj_factors(),
        )
        result = loader.load_bars(
            symbols=["000001.SZ"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 4, tzinfo=TZ),
            adj_policy="pre",
        )
        jun1 = result.filter(pl.col("dt").dt.date() == date(2026, 6, 1))
        assert jun1["volume"].to_list()[0] == 1000.0  # unchanged
