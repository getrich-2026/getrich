"""Tests for Backtest factor integration — ctx.factor()."""

from datetime import datetime
from decimal import Decimal

import polars as pl

from getrich_backtest import (
    Backtest,
    BarContext,
    DataFrameBarLoader,
    OrderIntent,
    Strategy,
    get_shanghai_tz,
)


TZ = get_shanghai_tz()


class TestBacktestFactors:
    def test_ctx_factor_returns_preloaded_data(self) -> None:
        """ctx.factor('mom20') returns the pre-loaded factor DataFrame."""
        bars = pl.DataFrame(
            {
                "dt": [datetime(2026, 1, 15, 9, 30, tzinfo=TZ)],
                "symbol": ["000001.SZ"],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [1000.0],
            },
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )

        factors_df = pl.DataFrame(
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

        captured = None

        class FactorStrategy(Strategy):
            @property
            def name(self) -> str:
                return "FactorStrategy"

            def on_bar(self, ctx: BarContext) -> list[OrderIntent] | None:
                nonlocal captured
                captured = ctx.factor("mom20")
                return None

        bt = Backtest(
            strategy=FactorStrategy(),
            bar_loader=DataFrameBarLoader(bars, factors_df=factors_df),
            symbols=["000001.SZ"],
            start=datetime(2026, 1, 15, tzinfo=TZ),
            end=datetime(2026, 1, 16, tzinfo=TZ),
            initial_cash=Decimal("100000"),
        )
        bt.run()

        assert captured is not None
        assert "dt" in captured.columns
        assert "symbol" in captured.columns
        assert "value" in captured.columns
        assert captured["value"].to_list() == [0.05]

    def test_ctx_factor_unknown_name_returns_none(self) -> None:
        """Requesting an unknown factor name returns None."""
        bars = pl.DataFrame(
            {
                "dt": [datetime(2026, 1, 15, 9, 30, tzinfo=TZ)],
                "symbol": ["000001.SZ"],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [1000.0],
            },
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )

        factors_df = pl.DataFrame(
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

        captured = None

        class FactorStrategy(Strategy):
            @property
            def name(self) -> str:
                return "FactorStrategy"

            def on_bar(self, ctx: BarContext) -> list[OrderIntent] | None:
                nonlocal captured
                captured = ctx.factor("unknown_factor")
                return None

        bt = Backtest(
            strategy=FactorStrategy(),
            bar_loader=DataFrameBarLoader(bars, factors_df=factors_df),
            symbols=["000001.SZ"],
            start=datetime(2026, 1, 15, tzinfo=TZ),
            end=datetime(2026, 1, 16, tzinfo=TZ),
            initial_cash=Decimal("100000"),
        )
        bt.run()

        assert captured is None

    def test_ctx_factor_no_factors_loaded_returns_none(self) -> None:
        """Without factors_df, ctx.factor() returns None."""
        bars = pl.DataFrame(
            {
                "dt": [datetime(2026, 1, 15, 9, 30, tzinfo=TZ)],
                "symbol": ["000001.SZ"],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [1000.0],
            },
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )

        captured = None

        class FactorStrategy(Strategy):
            @property
            def name(self) -> str:
                return "FactorStrategy"

            def on_bar(self, ctx: BarContext) -> list[OrderIntent] | None:
                nonlocal captured
                captured = ctx.factor("mom20")
                return None

        bt = Backtest(
            strategy=FactorStrategy(),
            bar_loader=DataFrameBarLoader(bars),
            symbols=["000001.SZ"],
            start=datetime(2026, 1, 15, tzinfo=TZ),
            end=datetime(2026, 1, 16, tzinfo=TZ),
            initial_cash=Decimal("100000"),
        )
        bt.run()

        assert captured is None
