"""Tests for DuckDBBarLoader using real DuckDB in-memory database."""

import tempfile
from datetime import datetime
from decimal import Decimal

import polars as pl
import pytest
from gr_backtest import (
    Backtest,
    BarContext,
    DataLoadError,
    DuckDBBarLoader,
    OrderIntent,
    Side,
    Strategy,
    get_shanghai_tz,
)


TZ = get_shanghai_tz()


def _make_bars() -> pl.DataFrame:
    """Create 3 days of OHLCV bars for symbols A and B."""
    rows = []
    for day in range(1, 4):
        for sym, base_close in [("A", 100.0), ("B", 50.0)]:
            dt = datetime(2026, 6, day, 9, 30, tzinfo=TZ)
            rows.append(
                {
                    "dt": dt,
                    "symbol": sym,
                    "open": base_close + day * 1.0,
                    "high": base_close + day * 1.5,
                    "low": base_close + day * 0.5,
                    "close": base_close + day * 1.0,
                    "volume": 1000.0 * day,
                }
            )
    return pl.DataFrame(
        rows,
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


# ---------------------------------------------------------------------------
# DuckDBBarLoader tests
# ---------------------------------------------------------------------------


class TestDuckDBBarLoader:
    def test_load_bars_basic(self) -> None:
        """Basic query returns all rows within the time range."""
        loader = DuckDBBarLoader()
        bars = _make_bars()
        loader.register_df("md_bars_1d", bars)

        result = loader.load_bars(
            symbols=["A", "B"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 4, tzinfo=TZ),
        )
        assert result.height == 6  # 2 symbols * 3 days
        assert result.columns == ["dt", "symbol", "open", "high", "low", "close", "volume"]

    def test_load_bars_filter_symbols(self) -> None:
        """Only requested symbols are returned."""
        loader = DuckDBBarLoader()
        loader.register_df("md_bars_1d", _make_bars())

        result = loader.load_bars(
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 4, tzinfo=TZ),
        )
        assert result.height == 3  # only A, 3 days
        assert list(result["symbol"].unique()) == ["A"]

    def test_load_bars_all_symbols(self) -> None:
        """symbols=None returns all symbols."""
        loader = DuckDBBarLoader()
        loader.register_df("md_bars_1d", _make_bars())

        result = loader.load_bars(
            symbols=None,
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 4, tzinfo=TZ),
        )
        # All 6 rows (2 symbols × 3 days)
        assert result.height == 6

    def test_load_bars_time_range(self) -> None:
        """Only bars within [start, end) are returned."""
        loader = DuckDBBarLoader()
        loader.register_df("md_bars_1d", _make_bars())

        result = loader.load_bars(
            symbols=["A", "B"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),  # excludes June 3
        )
        # 2 symbols × 2 days (June 1, 2)
        assert result.height == 4

    def test_load_bars_column_projection(self) -> None:
        """columns parameter only filters optional columns; required always present."""
        loader = DuckDBBarLoader()
        loader.register_df("md_bars_1d", _make_bars())

        result = loader.load_bars(
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 4, tzinfo=TZ),
            # Include all required + optional projection is not possible since
            # validate_bar_schema requires all BAR_REQUIRED_COLUMNS.
            columns=["dt", "symbol", "open", "high", "low", "close", "volume"],
        )
        assert result.columns == ["dt", "symbol", "open", "high", "low", "close", "volume"]

    def test_load_bars_columns_missing_required_raises(self) -> None:
        """columns missing required column raises DataLoadError."""
        loader = DuckDBBarLoader()
        loader.register_df("md_bars_1d", _make_bars())
        with pytest.raises(DataLoadError, match="required bar columns"):
            loader.load_bars(
                symbols=["A"],
                start=datetime(2026, 6, 1, tzinfo=TZ),
                end=datetime(2026, 6, 4, tzinfo=TZ),
                columns=["dt", "symbol"],
            )

    def test_load_bars_empty_result(self) -> None:
        """Empty result returns empty DataFrame with valid schema."""
        loader = DuckDBBarLoader()
        loader.register_df("md_bars_1d", _make_bars())

        result = loader.load_bars(
            symbols=["NONEXISTENT"],
            start=datetime(2026, 1, 1, tzinfo=TZ),
            end=datetime(2026, 1, 2, tzinfo=TZ),
        )
        assert result.is_empty()

    def test_table_name_default(self) -> None:
        """Default table name when no asset_class."""
        name = DuckDBBarLoader._table_name(None, "1d")
        assert name == "md_bars_1d"

    def test_table_name_with_asset_class(self) -> None:
        """Table name includes asset_class when provided."""
        name = DuckDBBarLoader._table_name("equity_a", "1d")
        assert name == "md_bars_equity_a_1d"

    def test_register_parquet(self) -> None:
        """Parquet file can be registered and queried."""
        loader = DuckDBBarLoader()
        bars = _make_bars()

        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
            bars.write_parquet(f.name)
            parquet_path = f.name

        try:
            loader.register_parquet("md_bars_1d", parquet_path)
            result = loader.load_bars(
                symbols=["A"],
                start=datetime(2026, 6, 1, tzinfo=TZ),
                end=datetime(2026, 6, 4, tzinfo=TZ),
            )
            assert result.height == 3
        finally:
            import os

            os.unlink(parquet_path)

    def test_schema_validation_passes(self) -> None:
        """Result passes validate_bar_schema."""
        from gr_backtest.data.schema import validate_bar_schema

        loader = DuckDBBarLoader()
        loader.register_df("md_bars_1d", _make_bars())

        result = loader.load_bars(
            symbols=["A", "B"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 4, tzinfo=TZ),
        )
        # Should not raise
        validated = validate_bar_schema(result)
        assert validated.height == 6

    def test_integration_via_backtest_run(self) -> None:
        """DuckDBBarLoader can be used with Backtest.run()."""

        class BuyFirstBar(Strategy):
            @property
            def name(self) -> str:
                return "BuyFirst"

            def on_bar(self, ctx: BarContext) -> list[OrderIntent] | None:
                if ctx.bar["dt"].to_list()[0] == datetime(2026, 6, 1, 9, 30, tzinfo=TZ):
                    return [OrderIntent(symbol="A", side=Side.BUY, qty=Decimal("1"))]
                return None

        loader = DuckDBBarLoader()
        loader.register_df("md_bars_1d", _make_bars())

        bt = Backtest(
            strategy=BuyFirstBar(),
            bar_loader=loader,
            symbols=["A", "B"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 4, tzinfo=TZ),
            initial_cash=Decimal("100000"),
        )
        result = bt.run()
        assert result.strategy_name == "BuyFirst"
        assert len(result.fills) == 1
        assert result.fills[0].symbol == "A"


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestDuckDBBarLoaderProtocol:
    def test_is_bar_loader(self) -> None:
        """DuckDBBarLoader satisfies the BarLoader protocol."""
        loader = DuckDBBarLoader()
        assert hasattr(loader, "load_bars")
        assert callable(loader.load_bars)
