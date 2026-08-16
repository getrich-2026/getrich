"""Tests for DuckDBBarLoader.iter_bars() using real DuckDB in-memory."""

from datetime import datetime

import polars as pl
from gr_backtest import DuckDBBarLoader, get_shanghai_tz


TZ = get_shanghai_tz()


def _make_3month_bars() -> pl.DataFrame:
    """Create daily bars for Jan/Feb/Mar 2026 for two symbols."""
    rows: list[dict] = []
    for month in (1, 2, 3):
        for day in (1, 5, 10, 15, 20, 25):
            if month == 2 and day > 20:
                continue
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


class TestDuckDBBarLoaderIterBars:
    def test_iter_bars_monthly_chunk_count(self) -> None:
        """Yields one chunk per month."""
        loader = DuckDBBarLoader()
        loader.register_df("md_bars_1d", _make_3month_bars())

        chunks = list(
            loader.iter_bars(
                symbols=None,
                start=datetime(2026, 1, 1, tzinfo=TZ),
                end=datetime(2026, 4, 1, tzinfo=TZ),
                chunk="month",
            )
        )
        assert len(chunks) == 3

    def test_iter_bars_monthly_total_rows(self) -> None:
        """Total rows across chunks equals full load."""
        bars = _make_3month_bars()
        loader = DuckDBBarLoader()
        loader.register_df("md_bars_1d", bars)

        chunks = list(
            loader.iter_bars(
                symbols=None,
                start=datetime(2026, 1, 1, tzinfo=TZ),
                end=datetime(2026, 4, 1, tzinfo=TZ),
                chunk="month",
            )
        )
        total = sum(c.height for c in chunks)
        assert total == bars.height

    def test_iter_bars_symbol_filter(self) -> None:
        """Symbol filter applied per chunk."""
        loader = DuckDBBarLoader()
        loader.register_df("md_bars_1d", _make_3month_bars())

        chunks = list(
            loader.iter_bars(
                symbols=["A"],
                start=datetime(2026, 1, 1, tzinfo=TZ),
                end=datetime(2026, 4, 1, tzinfo=TZ),
                chunk="month",
            )
        )
        assert len(chunks) == 3
        for chunk in chunks:
            symbols = chunk["symbol"].unique().to_list()
            assert symbols == ["A"]
