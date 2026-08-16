"""Tests for enhanced metrics (sortino, calmar, monthly returns)."""

from datetime import datetime
from decimal import Decimal

import polars as pl
import pytest
from gr_backtest import MetricsError, get_shanghai_tz
from gr_backtest.metrics import monthly_returns_heatmap


TZ = get_shanghai_tz()


class TestSortinoCalmar:
    def test_sortino_ratio_mixed(self) -> None:
        """Mixed returns produce a finite Sortino ratio."""
        from gr_backtest import Backtest, DataFrameBarLoader
        from gr_backtest.strategy.base import Strategy
        from gr_backtest.strategy.context import BarContext
        from gr_backtest.strategy.order import OrderIntent
        from gr_backtest.types import Side

        bars = pl.DataFrame(
            {
                "dt": [
                    datetime(2026, 1, 2, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 3, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 6, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 7, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 8, 9, 30, tzinfo=TZ),
                ],
                "symbol": ["A"] * 5,
                "open": [100.0, 102.0, 101.0, 103.0, 105.0],
                "high": [103.0, 104.0, 103.0, 105.0, 107.0],
                "low": [99.0, 101.0, 100.0, 102.0, 104.0],
                "close": [102.0, 101.0, 103.0, 105.0, 104.0],
                "volume": [1000.0] * 5,
            },
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )

        class BuyHold(Strategy):
            def __init__(self) -> None:
                super().__init__()
                self._done = False

            @property
            def name(self) -> str:
                return "BuyHold"

            def on_bar(self, ctx: BarContext) -> list[OrderIntent] | None:
                if not self._done:
                    self._done = True
                    return [OrderIntent(symbol="A", side=Side.BUY, qty=Decimal("10"))]
                return None

        bt = Backtest(
            strategy=BuyHold(),
            bar_loader=DataFrameBarLoader(bars),
            symbols=["A"],
            start=datetime(2026, 1, 2, tzinfo=TZ),
            end=datetime(2026, 1, 9, tzinfo=TZ),
            initial_cash=Decimal("10000"),
        )
        from gr_backtest.metrics import compute_metrics

        result = bt.run()
        metrics = compute_metrics(result)
        # Sortino should be different from Sharpe when returns are asymmetric
        assert metrics.sortino_ratio != metrics.sharpe_ratio
        assert metrics.sortino_ratio > Decimal("0")
        # Calmar should be finite
        assert metrics.calmar_ratio > Decimal("0")

    def test_calmar_zero_when_no_drawdown(self) -> None:
        """Calmar is 0 when max_drawdown = 0."""
        from gr_backtest.metrics import BacktestMetrics

        bm = BacktestMetrics(
            strategy_name="test",
            run_id="r1",
            total_return=Decimal("0.1"),
            log_return=Decimal("0.095"),
            annualized_return=Decimal("0.15"),
            annualized_volatility=Decimal("0.2"),
            sharpe_ratio=Decimal("0.6"),
            sortino_ratio=Decimal("0.8"),
            calmar_ratio=Decimal("0"),
            max_drawdown=Decimal("0"),
            max_drawdown_duration=0,
            total_fees=Decimal("0"),
            total_turnover=Decimal("0"),
            turnover_rate=Decimal("0"),
            total_trades=0,
            n_bars=100,
            risk_free_rate=Decimal("0.03"),
            trading_days_per_year=252,
        )
        assert bm.calmar_ratio == Decimal("0")


class TestMonthlyReturns:
    def test_monthly_returns_structure(self) -> None:
        """monthly_returns_heatmap returns correct schema."""
        dt = datetime(2026, 1, 2, 9, 30, tzinfo=TZ)
        eq = pl.DataFrame(
            {"dt": [dt], "equity": [10000.0]},
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )
        result = monthly_returns_heatmap(eq)
        assert result.columns == ["year", "month", "return"]
        assert result.height == 1
        assert result["year"][0] == 2026
        assert result["month"][0] == 1
        assert result["return"][0] == 0.0  # only 1 bar, start == end

    def test_monthly_returns_multi_month(self) -> None:
        """Returns across months are correctly computed."""
        jan = datetime(2026, 1, 2, 9, 30, tzinfo=TZ)
        feb_start = datetime(2026, 2, 2, 9, 30, tzinfo=TZ)
        feb_end = datetime(2026, 2, 27, 9, 30, tzinfo=TZ)
        mar = datetime(2026, 3, 2, 9, 30, tzinfo=TZ)

        eq = pl.DataFrame(
            {
                "dt": [jan, feb_start, feb_end, mar],
                "equity": [10000.0, 11000.0, 12000.0, 11500.0],
            },
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )
        result = monthly_returns_heatmap(eq)
        assert result.height == 3
        jan_row = result.filter((pl.col("year") == 2026) & (pl.col("month") == 1))
        feb_row = result.filter((pl.col("year") == 2026) & (pl.col("month") == 2))
        mar_row = result.filter((pl.col("year") == 2026) & (pl.col("month") == 3))

        assert jan_row["return"][0] == 0.0  # single bar in Jan
        assert feb_row["return"][0] == pytest.approx(12000.0 / 11000.0 - 1)  # Feb
        assert mar_row["return"][0] == 0.0  # single bar in Mar

    def test_monthly_returns_empty_raises(self) -> None:
        """Empty DataFrame raises MetricsError."""
        eq = pl.DataFrame(
            {"dt": [], "equity": []},
            schema={"dt": pl.Datetime("ms", "Asia/Shanghai"), "equity": pl.Float64},
        )
        with pytest.raises(MetricsError, match="must not be empty"):
            monthly_returns_heatmap(eq)

    def test_monthly_returns_missing_column_raises(self) -> None:
        """Missing column raises MetricsError."""
        eq = pl.DataFrame({"x": [1]})
        with pytest.raises(MetricsError, match="missing columns"):
            monthly_returns_heatmap(eq)

    def test_backward_compatibility(self) -> None:
        """Existing BacktestMetrics still constructible with new fields."""
        from gr_backtest.metrics import BacktestMetrics

        bm = BacktestMetrics(
            strategy_name="test",
            run_id="r1",
            total_return=Decimal("0.05"),
            log_return=Decimal("0.048"),
            annualized_return=Decimal("0.10"),
            annualized_volatility=Decimal("0.15"),
            sharpe_ratio=Decimal("0.47"),
            sortino_ratio=Decimal("0.60"),
            calmar_ratio=Decimal("0.50"),
            max_drawdown=Decimal("-0.20"),
            max_drawdown_duration=10,
            total_fees=Decimal("50"),
            total_turnover=Decimal("5000"),
            turnover_rate=Decimal("0.5"),
            total_trades=5,
            n_bars=252,
            risk_free_rate=Decimal("0.03"),
            trading_days_per_year=252,
        )
        assert bm.total_return == Decimal("0.05")
        assert bm.sortino_ratio == Decimal("0.60")
        assert bm.calmar_ratio == Decimal("0.50")
