"""Tests for Backtest calendar integration."""

from datetime import date, datetime
from decimal import Decimal

import polars as pl

from getrich_backtest import (
    Backtest,
    BarContext,
    Calendar,
    DataFrameBarLoader,
    OrderIntent,
    Strategy,
    get_shanghai_tz,
)


TZ = get_shanghai_tz()


class TestBacktestCalendar:
    def test_calendar_filters_non_trading_days(self) -> None:
        """With a calendar, non-trading days are skipped in the bar loop."""
        bars = pl.DataFrame(
            {
                "dt": [
                    datetime(2026, 6, 1, 9, 30, tzinfo=TZ),
                    datetime(2026, 6, 2, 9, 30, tzinfo=TZ),
                    datetime(2026, 6, 3, 9, 30, tzinfo=TZ),
                ],
                "symbol": ["A", "A", "A"],
                "open": [100.0, 101.0, 102.0],
                "high": [101.0, 102.0, 103.0],
                "low": [99.0, 100.0, 101.0],
                "close": [100.5, 101.5, 102.5],
                "volume": [1000.0, 1000.0, 1000.0],
            },
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )
        # June 3 (Wed) is NOT a trading day in this calendar
        cal = Calendar(
            trading_days=(
                datetime(2026, 6, 1, 9, 30, tzinfo=TZ),
                datetime(2026, 6, 2, 9, 30, tzinfo=TZ),
            )
        )

        call_count = 0

        class CountBars(Strategy):
            @property
            def name(self) -> str:
                return "CountBars"

            def on_bar(self, ctx: BarContext) -> list[OrderIntent] | None:
                nonlocal call_count
                call_count += 1
                return None

        bt = Backtest(
            strategy=CountBars(),
            bar_loader=DataFrameBarLoader(bars),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 4, tzinfo=TZ),
            initial_cash=Decimal("100000"),
            calendar=cal,
        )
        bt.run()
        # Only 2 trading days, not 3
        assert call_count == 2

    def test_calendar_injected_into_context(self) -> None:
        """Calendar is accessible via ctx.calendar during on_bar."""
        bars = pl.DataFrame(
            {
                "dt": [
                    datetime(2026, 6, 1, 9, 30, tzinfo=TZ),
                ],
                "symbol": ["A"],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [1000.0],
            },
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )
        cal = Calendar(trading_days=(datetime(2026, 6, 1, 9, 30, tzinfo=TZ),))

        captured_cal = None

        class CheckCalendar(Strategy):
            @property
            def name(self) -> str:
                return "CheckCalendar"

            def on_bar(self, ctx: BarContext) -> list[OrderIntent] | None:
                nonlocal captured_cal
                captured_cal = ctx.calendar
                return None

        bt = Backtest(
            strategy=CheckCalendar(),
            bar_loader=DataFrameBarLoader(bars),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 2, tzinfo=TZ),
            initial_cash=Decimal("100000"),
            calendar=cal,
        )
        bt.run()
        assert captured_cal is not None
        assert captured_cal.is_trading_date(date(2026, 6, 1))
        assert not captured_cal.is_trading_date(date(2026, 6, 2))

    def test_no_calendar_does_not_filter(self) -> None:
        """Without a calendar, all bars are processed."""
        bars = pl.DataFrame(
            {
                "dt": [
                    datetime(2026, 6, 1, 9, 30, tzinfo=TZ),
                    datetime(2026, 6, 2, 9, 30, tzinfo=TZ),
                    datetime(2026, 6, 3, 9, 30, tzinfo=TZ),
                ],
                "symbol": ["A", "A", "A"],
                "open": [100.0, 101.0, 102.0],
                "high": [101.0, 102.0, 103.0],
                "low": [99.0, 100.0, 101.0],
                "close": [100.5, 101.5, 102.5],
                "volume": [1000.0, 1000.0, 1000.0],
            },
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )

        call_count = 0

        class CountBars(Strategy):
            @property
            def name(self) -> str:
                return "CountBars"

            def on_bar(self, ctx: BarContext) -> list[OrderIntent] | None:
                nonlocal call_count
                call_count += 1
                return None

        bt = Backtest(
            strategy=CountBars(),
            bar_loader=DataFrameBarLoader(bars),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 4, tzinfo=TZ),
            initial_cash=Decimal("100000"),
        )
        bt.run()
        # All 3 bars processed
        assert call_count == 3
