"""Tests for benchmark comparison metrics."""

from datetime import datetime, timedelta
from decimal import Decimal

import polars as pl
import pytest
from gr_backtest import (
    Benchmark,
    BenchmarkCompareResult,
    BenchmarkError,
    compute_benchmark_comparison,
    get_shanghai_tz,
)


TZ = get_shanghai_tz()
_DECIMAL_ZERO = Decimal("0")


def _equity_curve(values: list[float], start: datetime | None = None) -> pl.DataFrame:
    """Build a minimal equity curve DataFrame."""
    if start is None:
        start = datetime(2026, 1, 2, 9, 30, tzinfo=TZ)
    dts = [
        datetime(year, month, day, 9, 30, tzinfo=TZ)
        for year, month, day in (
            (2026, 1, 2),
            (2026, 1, 3),
            (2026, 1, 6),
            (2026, 1, 7),
            (2026, 1, 8),
            (2026, 1, 9),
        )
    ][: len(values)]
    return pl.DataFrame(
        {"dt": dts, "equity": values},
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


class TestBenchmarkCompareResult:
    def test_frozen(self) -> None:
        """BenchmarkCompareResult is frozen (immutable)."""
        bc = BenchmarkCompareResult(
            benchmark_return=Decimal("0.05"),
            benchmark_annualized_return=Decimal("0.10"),
            benchmark_volatility=Decimal("0.15"),
            benchmark_max_drawdown=Decimal("-0.10"),
            excess_return=Decimal("0.02"),
            alpha=Decimal("0.03"),
            beta=Decimal("0.80"),
            tracking_error=Decimal("0.12"),
            information_ratio=Decimal("0.50"),
            excess_max_drawdown=Decimal("-0.05"),
        )
        with pytest.raises(AttributeError):
            bc.alpha = Decimal("0.99")  # type: ignore[misc]

    def test_to_dict(self) -> None:
        """to_dict serializes all Decimal fields as strings."""
        bc = BenchmarkCompareResult(
            benchmark_return=Decimal("0.05"),
            benchmark_annualized_return=Decimal("0.10"),
            benchmark_volatility=Decimal("0.15"),
            benchmark_max_drawdown=Decimal("-0.10"),
            excess_return=Decimal("0.02"),
            alpha=Decimal("0.03"),
            beta=Decimal("0.80"),
            tracking_error=Decimal("0.12"),
            information_ratio=Decimal("0.50"),
            excess_max_drawdown=Decimal("-0.05"),
        )
        d = bc.to_dict()
        assert d["alpha"] == "0.03"
        assert d["beta"] == "0.80"
        assert d["benchmark_return"] == "0.05"
        assert d["excess_max_drawdown"] == "-0.05"


class TestComputeBenchmarkComparison:
    def test_perfect_correlation(self) -> None:
        """Identical strategy and benchmark produce beta=1, alpha=0, TE=0."""
        values = [100000.0, 101000.0, 102000.0, 101500.0, 103000.0, 104000.0]
        eq_s = _equity_curve(values)
        eq_b = _equity_curve(values.copy())

        bc = compute_benchmark_comparison(eq_s, eq_b)

        assert bc.beta == pytest.approx(Decimal("1.0"), abs=1e-10)
        assert abs(bc.alpha) < Decimal("0.0001")
        assert bc.tracking_error == pytest.approx(Decimal("0"), abs=1e-10)
        assert bc.information_ratio == pytest.approx(Decimal("0"), abs=1e-10)
        assert abs(bc.excess_return) < Decimal("0.0001")

    def test_higher_return(self) -> None:
        """Strategy outperforming benchmark produces positive alpha."""
        eq_s = _equity_curve([100000.0, 102000.0, 104000.0, 103000.0, 106000.0, 108000.0])
        eq_b = _equity_curve([100000.0, 100500.0, 101000.0, 100800.0, 102000.0, 103000.0])

        bc = compute_benchmark_comparison(eq_s, eq_b)

        assert bc.excess_return > _DECIMAL_ZERO
        assert bc.alpha > _DECIMAL_ZERO

    def test_lower_return(self) -> None:
        """Strategy underperforming benchmark produces negative alpha."""
        eq_s = _equity_curve([100000.0, 100200.0, 100500.0, 100300.0, 101000.0, 101500.0])
        eq_b = _equity_curve([100000.0, 101000.0, 102000.0, 101500.0, 103000.0, 104000.0])

        bc = compute_benchmark_comparison(eq_s, eq_b)

        assert bc.excess_return < _DECIMAL_ZERO
        assert bc.alpha < _DECIMAL_ZERO

    def test_no_volatility(self) -> None:
        """Both curves flat produce TE=0."""
        eq_s = _equity_curve([100000.0] * 6)
        eq_b = _equity_curve([100000.0] * 6)

        bc = compute_benchmark_comparison(eq_s, eq_b)

        assert bc.tracking_error == pytest.approx(Decimal("0"), abs=1e-10)
        assert bc.information_ratio == pytest.approx(Decimal("0"), abs=1e-10)
        assert abs(bc.beta) < Decimal("0.0001") or bc.beta == pytest.approx(Decimal("0"), abs=1e-10)

    def test_benchmark_metrics(self) -> None:
        """Benchmark standalone metrics are computed correctly."""
        eq_s = _equity_curve([100000.0, 101000.0, 102000.0, 101500.0, 103000.0, 104000.0])
        eq_b = _equity_curve([100000.0, 102000.0, 104000.0, 103000.0, 106000.0, 108000.0])

        bc = compute_benchmark_comparison(eq_s, eq_b)

        # Benchmark total return: (108000 - 100000) / 100000 = 0.08
        assert bc.benchmark_return == pytest.approx(Decimal("0.08"), abs=1e-10)
        # Benchmark max drawdown should be negative
        assert bc.benchmark_max_drawdown < _DECIMAL_ZERO
        # Benchmark volatility should be positive (returns fluctuate)
        assert bc.benchmark_volatility > _DECIMAL_ZERO

    def test_empty_strategy_curve(self) -> None:
        """Empty strategy curve raises BenchmarkError."""
        eq_s = pl.DataFrame(
            {"dt": [], "equity": []},
            schema={"dt": pl.Datetime("ms", "Asia/Shanghai"), "equity": pl.Float64},
        )
        eq_b = _equity_curve([100000.0, 101000.0])

        with pytest.raises(BenchmarkError, match="must not be empty"):
            compute_benchmark_comparison(eq_s, eq_b)

    def test_empty_benchmark_curve(self) -> None:
        """Empty benchmark curve raises BenchmarkError."""
        eq_s = _equity_curve([100000.0, 101000.0])
        eq_b = pl.DataFrame(
            {"dt": [], "equity": []},
            schema={"dt": pl.Datetime("ms", "Asia/Shanghai"), "equity": pl.Float64},
        )

        with pytest.raises(BenchmarkError, match="must not be empty"):
            compute_benchmark_comparison(eq_s, eq_b)

    def test_missing_columns(self) -> None:
        """Missing columns raise BenchmarkError."""
        eq_s = pl.DataFrame({"x": [1, 2]})
        eq_b = pl.DataFrame({"x": [1, 2]})

        with pytest.raises(BenchmarkError, match="missing columns"):
            compute_benchmark_comparison(eq_s, eq_b)

    def test_date_alignment(self) -> None:
        """Different date ranges align on intersection."""
        eq_s = pl.DataFrame(
            {
                "dt": [
                    datetime(2026, 1, 2, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 3, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 6, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 7, 9, 30, tzinfo=TZ),
                ],
                "equity": [100000.0, 101000.0, 102000.0, 103000.0],
            },
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )
        # Benchmark has extra dates before and after
        eq_b = pl.DataFrame(
            {
                "dt": [
                    datetime(2026, 1, 1, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 2, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 3, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 6, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 7, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 8, 9, 30, tzinfo=TZ),
                ],
                "equity": [99000.0, 100000.0, 100500.0, 101000.0, 102000.0, 103000.0],
            },
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )

        # Should align on 4 common dates (Jan 2, 3, 6, 7)
        bc = compute_benchmark_comparison(eq_s, eq_b)
        # Should not raise, and metrics should be finite
        assert bc.tracking_error >= _DECIMAL_ZERO
        assert isinstance(bc.alpha, Decimal)

    def test_fewer_than_2_aligned_bars(self) -> None:
        """Fewer than 2 aligned bars raises BenchmarkError."""
        eq_s = pl.DataFrame(
            {
                "dt": [datetime(2026, 1, 2, 9, 30, tzinfo=TZ)],
                "equity": [100000.0],
            },
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )
        eq_b = pl.DataFrame(
            {
                "dt": [datetime(2026, 1, 2, 9, 30, tzinfo=TZ)],
                "equity": [100000.0],
            },
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )

        with pytest.raises(BenchmarkError, match="at least 2"):
            compute_benchmark_comparison(eq_s, eq_b)

    def test_excess_max_drawdown(self) -> None:
        """Excess max drawdown is computed correctly."""
        # Strategy starts strong but then underperforms
        eq_s = _equity_curve([100000.0, 105000.0, 102000.0, 101000.0, 100500.0, 100000.0])
        eq_b = _equity_curve([100000.0, 100000.0, 100000.0, 100000.0, 100000.0, 100000.0])

        bc = compute_benchmark_comparison(eq_s, eq_b)

        # Excess curve goes from 0 to +5000 to -0, so there IS a drawdown
        # Excess: [0, 5000, 2000, 1000, 500, 0]
        # Max dd from peak 5000 to trough 0 = -5000/5000 = -1.0
        assert bc.excess_max_drawdown < _DECIMAL_ZERO
        # With flat benchmark and strategy returning 0, excess max dd ≈ -1.0
        # (peak at 5000 above initial, trough at initial)
        assert bc.excess_max_drawdown <= Decimal("-0.99")

    def test_custom_risk_free_rate(self) -> None:
        """Custom risk-free rate is accepted and produces finite alpha."""
        eq_s = _equity_curve([100000.0, 102000.0, 104000.0, 103000.0, 106000.0, 108000.0])
        eq_b = _equity_curve([100000.0, 100500.0, 101000.0, 100800.0, 102000.0, 103000.0])

        bc0 = compute_benchmark_comparison(eq_s, eq_b, risk_free_rate=Decimal("0"))
        bc3 = compute_benchmark_comparison(eq_s, eq_b, risk_free_rate=Decimal("0.03"))

        # Both should produce finite values
        assert isinstance(bc0.alpha, Decimal)
        assert isinstance(bc3.alpha, Decimal)
        # Alpha should differ with different risk-free rates
        assert bc0.alpha != bc3.alpha


class TestBenchmark:
    def test_from_equity_curve_valid(self) -> None:
        """Valid equity curve passes through."""
        df = _equity_curve([100000.0, 101000.0])
        result = Benchmark.from_equity_curve(df)
        assert result is df  # pass-through

    def test_from_equity_curve_missing_column(self) -> None:
        """Missing column raises BenchmarkError."""
        df = pl.DataFrame({"x": [1, 2]})
        with pytest.raises(BenchmarkError, match="missing columns"):
            Benchmark.from_equity_curve(df)

    def test_from_equity_curve_empty(self) -> None:
        """Empty curve raises BenchmarkError."""
        df = pl.DataFrame(
            {"dt": [], "equity": []},
            schema={"dt": pl.Datetime("ms", "Asia/Shanghai"), "equity": pl.Float64},
        )
        with pytest.raises(BenchmarkError, match="must not be empty"):
            Benchmark.from_equity_curve(df)

    def test_cash_factory(self) -> None:
        """Cash benchmark compounds correctly."""
        df = Benchmark.cash(
            initial_value=Decimal("100000"),
            annual_rate=Decimal("0.03"),
            periods=5,
        )
        assert df.height == 5
        assert df.columns == ["dt", "equity"]
        # First value should be initial_value
        assert df["equity"][0] == pytest.approx(100000.0, rel=1e-10)
        # Should be monotonically increasing
        assert all(df["equity"][i] < df["equity"][i + 1] for i in range(df.height - 1))

    def test_cash_with_dates(self) -> None:
        """Cash benchmark with start_dt generates datetime index."""
        df = Benchmark.cash(
            initial_value=Decimal("100000"),
            annual_rate=Decimal("0.03"),
            periods=3,
            start_dt="2026-01-01",
        )
        assert df.height == 3
        assert isinstance(df["dt"][0], datetime)

    def test_cash_negative_periods(self) -> None:
        """Periods < 1 raises BenchmarkError."""
        with pytest.raises(BenchmarkError, match="periods"):
            Benchmark.cash(
                initial_value=Decimal("100000"),
                annual_rate=Decimal("0.03"),
                periods=0,
            )


# ── Sub-daily benchmark comparison (P10 Phase 2) ────────────────────────────


class TestComputeBenchmarkComparisonSubDaily:
    def test_benchmark_comparison_subdaily(self) -> None:
        """Sub-daily equity curves produce sensible CAGR/vol in benchmark comparison."""
        # 5-minute bars for 3 days
        tz = get_shanghai_tz()
        start = datetime(2026, 1, 5, 9, 30, tzinfo=tz)
        dts_s: list[datetime] = []
        dts_b: list[datetime] = []
        for day_offset in range(3):
            base = start + timedelta(days=day_offset)
            for minute_offset in range(0, 60, 5):
                dts_s.append(base + timedelta(minutes=minute_offset))
                dts_b.append(base + timedelta(minutes=minute_offset))

        eq_s = pl.DataFrame(
            {
                "dt": dts_s,
                "equity": [100000.0 + i * 50 for i in range(len(dts_s))],
            },
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )
        eq_b = pl.DataFrame(
            {
                "dt": dts_b,
                "equity": [100000.0 + i * 20 for i in range(len(dts_b))],
            },
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )

        bc = compute_benchmark_comparison(eq_s, eq_b)
        # Should complete and produce reasonable values
        assert bc.benchmark_return > _DECIMAL_ZERO
        assert bc.excess_return != _DECIMAL_ZERO
        assert bc.benchmark_volatility >= _DECIMAL_ZERO
        assert isinstance(bc.beta, Decimal)

    def test_benchmark_integer_dt_passthrough(self) -> None:
        """Benchmark.cash() with integer dt passes through _to_daily_equity."""
        # ``Benchmark.cash()`` generates near-deterministic returns (constant
        # daily compounding), so Var(r_b) ≈ 0 and beta is numerically
        # unstable.  The point of this test is that integer dt doesn't crash.
        cash_df = Benchmark.cash(
            initial_value=Decimal("100000"),
            annual_rate=Decimal("0.03"),
            periods=10,
        )
        # Strategy: linearly increasing equity
        eq_s = pl.DataFrame(
            {"dt": list(range(10)), "equity": [100000.0 + i * 1000 for i in range(10)]},
            schema_overrides={"dt": pl.Int64, "equity": pl.Float64},
        )

        bc = compute_benchmark_comparison(eq_s, cash_df)
        # Should complete without error; alpha is finite
        assert isinstance(bc.alpha, Decimal)
        assert isinstance(bc.beta, Decimal)
