"""Tests for DataFrameBarLoader.iter_bars()."""

from datetime import datetime

import polars as pl
from gr_backtest import DataFrameBarLoader, get_shanghai_tz


TZ = get_shanghai_tz()


def _make_3month_bars() -> pl.DataFrame:
    """Create daily bars for Jan/Feb/Mar 2026 for two symbols."""
    rows: list[dict] = []
    for month in (1, 2, 3):
        for day in (1, 5, 10, 15, 20, 25):
            if month == 2 and day > 20:
                continue  # skip end-of-Feb
            dt = datetime(2026, month, day, 9, 30, tzinfo=TZ)
            for sym in ("A", "B"):
                rows.append(
                    {
                        "dt": dt,
                        "symbol": sym,
                        "open": 100.0,
                        "high": 101.0,
                        "low": 99.0,
                        "close": 100.5,
                        "volume": 1000.0,
                    }
                )
    return pl.DataFrame(
        rows,
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


class TestDataFrameBarLoaderIterBars:
    def test_iter_bars_monthly(self) -> None:
        """Yields one chunk per month in the range."""
        bars = _make_3month_bars()
        loader = DataFrameBarLoader(bars)

        chunks = list(
            loader.iter_bars(
                symbols=None,
                start=datetime(2026, 1, 1, tzinfo=TZ),
                end=datetime(2026, 4, 1, tzinfo=TZ),
                chunk="month",
            )
        )
        assert len(chunks) == 3  # Jan, Feb, Mar

    def test_iter_bars_monthly_chunks_are_partitioned(self) -> None:
        """Chunks are non-overlapping and cover the full range."""
        bars = _make_3month_bars()
        loader = DataFrameBarLoader(bars)

        chunks = list(
            loader.iter_bars(
                symbols=None,
                start=datetime(2026, 1, 1, tzinfo=TZ),
                end=datetime(2026, 4, 1, tzinfo=TZ),
                chunk="month",
            )
        )
        total_rows = sum(c.height for c in chunks)
        assert total_rows == bars.height

    def test_iter_bars_quarterly(self) -> None:
        """Yields one chunk for quarter."""
        bars = _make_3month_bars()
        loader = DataFrameBarLoader(bars)

        chunks = list(
            loader.iter_bars(
                symbols=None,
                start=datetime(2026, 1, 1, tzinfo=TZ),
                end=datetime(2026, 4, 1, tzinfo=TZ),
                chunk="quarter",
            )
        )
        assert len(chunks) == 1  # Q1
        assert chunks[0].height == bars.height

    def test_iter_bars_yearly(self) -> None:
        """Yields one chunk for the full year."""
        bars = _make_3month_bars()
        loader = DataFrameBarLoader(bars)

        chunks = list(
            loader.iter_bars(
                symbols=None,
                start=datetime(2026, 1, 1, tzinfo=TZ),
                end=datetime(2026, 4, 1, tzinfo=TZ),
                chunk="year",
            )
        )
        assert len(chunks) == 1
        assert chunks[0].height == bars.height

    def test_iter_bars_weekly(self) -> None:
        """Yields weekly chunks."""
        bars = _make_3month_bars()
        loader = DataFrameBarLoader(bars)

        chunks = list(
            loader.iter_bars(
                symbols=None,
                start=datetime(2026, 1, 1, tzinfo=TZ),
                end=datetime(2026, 4, 1, tzinfo=TZ),
                chunk="week",
            )
        )
        assert len(chunks) >= 10  # ~12 weeks in 3 months

    def test_iter_bars_single_month(self) -> None:
        """Range within one month yields a single chunk."""
        bars = _make_3month_bars()
        loader = DataFrameBarLoader(bars)

        chunks = list(
            loader.iter_bars(
                symbols=None,
                start=datetime(2026, 1, 5, tzinfo=TZ),
                end=datetime(2026, 1, 25, tzinfo=TZ),
                chunk="month",
            )
        )
        assert len(chunks) == 1

    def test_iter_bars_empty(self) -> None:
        """Empty bar data yields one empty chunk."""
        bars = pl.DataFrame(
            {col: [] for col in ("dt", "symbol", "open", "high", "low", "close", "volume")},
            schema={
                "dt": pl.Datetime("ms", "Asia/Shanghai"),
                "symbol": pl.Utf8,
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
                "volume": pl.Float64,
            },
        )
        loader = DataFrameBarLoader(bars)

        chunks = list(
            loader.iter_bars(
                symbols=None,
                start=datetime(2026, 1, 1, tzinfo=TZ),
                end=datetime(2026, 4, 1, tzinfo=TZ),
                chunk="month",
            )
        )
        assert len(chunks) == 3
        assert all(c.is_empty() for c in chunks)

    def test_iter_bars_symbol_filter(self) -> None:
        """Symbol filter is applied per chunk."""
        bars = _make_3month_bars()
        loader = DataFrameBarLoader(bars)

        chunks = list(
            loader.iter_bars(
                symbols=["A"],
                start=datetime(2026, 1, 1, tzinfo=TZ),
                end=datetime(2026, 4, 1, tzinfo=TZ),
                chunk="month",
            )
        )
        for chunk in chunks:
            symbols = chunk["symbol"].unique().to_list()
            assert symbols == ["A"]

    def test_iter_bars_unknown_chunk(self) -> None:
        """Unknown chunk mode raises ValueError."""
        bars = _make_3month_bars()
        loader = DataFrameBarLoader(bars)

        import pytest

        with pytest.raises(ValueError, match="unknown chunk"):
            list(
                loader.iter_bars(
                    symbols=None,
                    start=datetime(2026, 1, 1, tzinfo=TZ),
                    end=datetime(2026, 4, 1, tzinfo=TZ),
                    chunk="decade",
                )
            )

    def test_protocol_structural_check(self) -> None:
        """DataFrameBarLoader satisfies the iter_bars Protocol contract."""
        from collections.abc import Generator

        loader = DataFrameBarLoader(
            pl.DataFrame(
                {
                    "dt": [],
                    "symbol": [],
                    "open": [],
                    "high": [],
                    "low": [],
                    "close": [],
                    "volume": [],
                },
                schema={
                    "dt": pl.Datetime("ms", "Asia/Shanghai"),
                    "symbol": pl.Utf8,
                    "open": pl.Float64,
                    "high": pl.Float64,
                    "low": pl.Float64,
                    "close": pl.Float64,
                    "volume": pl.Float64,
                },
            )
        )
        result = loader.iter_bars(
            symbols=None,
            start=datetime(2026, 1, 1, tzinfo=TZ),
            end=datetime(2026, 2, 1, tzinfo=TZ),
        )
        assert isinstance(result, Generator)
