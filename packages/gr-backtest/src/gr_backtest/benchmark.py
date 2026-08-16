"""Benchmark comparison metrics for backtest results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from math import sqrt

import numpy as np
import polars as pl

from gr_backtest.exceptions import MetricsError
from gr_backtest.time import get_shanghai_tz


_DECIMAL_ZERO = Decimal("0")


class BenchmarkError(MetricsError):
    """Raised when benchmark comparison inputs are invalid."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)


@dataclass(frozen=True)
class BenchmarkCompareResult:
    """Benchmark comparison metrics.

    Computed by comparing a strategy equity curve against a benchmark equity
    curve on aligned dates.  All annualized metrics assume ``periods_per_year``
    trading periods.
    """

    # -- Benchmark standalone metrics ----------------------------------------
    benchmark_return: Decimal
    """Total return of the benchmark over the aligned period."""

    benchmark_annualized_return: Decimal
    """Annualized (CAGR) return of the benchmark."""

    benchmark_volatility: Decimal
    """Annualized volatility of the benchmark daily returns."""

    benchmark_max_drawdown: Decimal
    """Maximum peak-to-trough drawdown of the benchmark (negative)."""

    # -- Comparison metrics --------------------------------------------------
    excess_return: Decimal
    """Strategy total return minus benchmark total return."""

    alpha: Decimal
    """Jensen's Alpha (annualized): excess return not explained by beta."""

    beta: Decimal
    """Systematic risk: Cov(r_s, r_b) / Var(r_b)."""

    tracking_error: Decimal
    """Annualized standard deviation of excess returns (r_s - r_b)."""

    information_ratio: Decimal
    """Annualized mean(r_s - r_b) / std(r_s - r_b)."""

    excess_max_drawdown: Decimal
    """Maximum drawdown of the cumulative excess (strategy - benchmark) curve.

    Both curves are normalized to the same initial value before computing
    the excess.
    """

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable dict (Decimal fields → str)."""
        return {
            "benchmark_return": str(self.benchmark_return),
            "benchmark_annualized_return": str(self.benchmark_annualized_return),
            "benchmark_volatility": str(self.benchmark_volatility),
            "benchmark_max_drawdown": str(self.benchmark_max_drawdown),
            "excess_return": str(self.excess_return),
            "alpha": str(self.alpha),
            "beta": str(self.beta),
            "tracking_error": str(self.tracking_error),
            "information_ratio": str(self.information_ratio),
            "excess_max_drawdown": str(self.excess_max_drawdown),
        }


def _to_daily_equity(eq_curve: pl.DataFrame) -> pl.DataFrame:
    """Downsample an equity curve to daily frequency.

    Integer-indexed curves (e.g. from ``Benchmark.cash()`` without
    ``start_dt``) pass through unchanged.  Datetime-indexed curves are
    grouped by date, taking the last equity per day.
    """
    if eq_curve["dt"].dtype == pl.Int64:
        return eq_curve
    return (
        eq_curve.with_columns(pl.col("dt").dt.truncate("1d").alias("_bucket"))
        .sort(["dt"])
        .group_by("_bucket", maintain_order=True)
        .agg(pl.col("equity").last())
        .rename({"_bucket": "dt"})
    )


def compute_benchmark_comparison(
    strategy_equity_curve: pl.DataFrame,
    benchmark_equity_curve: pl.DataFrame,
    *,
    risk_free_rate: Decimal = Decimal("0.03"),
    periods_per_year: int = 252,
) -> BenchmarkCompareResult:
    """Compute benchmark comparison metrics.

    Both curves are first downsampled to daily (if they carry sub-daily
    timestamps), then aligned by inner joining on the ``dt`` column.

    Parameters
    ----------
    strategy_equity_curve : pl.DataFrame
        Strategy equity curve with ``["dt", "equity"]`` columns, sorted by
        ``dt``.
    benchmark_equity_curve : pl.DataFrame
        Benchmark equity curve with ``["dt", "equity"]`` columns, sorted by
        ``dt``.
    risk_free_rate : Decimal
        Annualized risk-free rate used for alpha computation (default 3%).
    periods_per_year : int
        Number of trading periods per year for annualization (default 252).

    Returns
    -------
    BenchmarkCompareResult

    Raises
    ------
    BenchmarkError
        If inputs are degenerate (empty, missing columns, fewer than 2 aligned
        bars, or invalid ``periods_per_year``).
    """
    _validate_inputs(strategy_equity_curve, benchmark_equity_curve, periods_per_year)

    # Downsample to daily so annualization is frequency-independent
    strategy_daily = _to_daily_equity(strategy_equity_curve)
    benchmark_daily = _to_daily_equity(benchmark_equity_curve)

    # Align on common dates
    aligned = (
        strategy_daily.select("dt", pl.col("equity").alias("eq_s"))
        .join(
            benchmark_daily.select("dt", pl.col("equity").alias("eq_b")),
            on="dt",
            how="inner",
        )
        .sort("dt")
    )

    if aligned.height < 2:
        raise BenchmarkError(
            f"aligned equity curves must have at least 2 common bars (got {aligned.height})"
        )

    eq_s = aligned["eq_s"].to_numpy().astype("float64")
    eq_b = aligned["eq_b"].to_numpy().astype("float64")
    n_bars = aligned.height

    # Daily returns
    r_s = _returns(eq_s)
    r_b = _returns(eq_b)

    # -- Benchmark standalone metrics ---------------------------------------
    bm_return_val = _total_return(eq_b)
    bm_cagr = _cagr(eq_b, periods_per_year, n_bars)
    bm_vol = _annualized_vol(r_b, periods_per_year)
    bm_max_dd = _max_drawdown(eq_b)

    # -- Comparison metrics -------------------------------------------------
    beta_val = _beta(r_s, r_b)

    ann_strat_return = _cagr(eq_s, periods_per_year, n_bars)
    ann_rf = float(risk_free_rate)
    alpha_val = (ann_strat_return - ann_rf) - beta_val * (bm_cagr - ann_rf)

    excess = r_s - r_b
    mean_excess = float(excess.mean()) if len(excess) > 0 else 0.0
    std_excess = float(excess.std(ddof=1)) if len(excess) >= 2 else 0.0

    ir_val = (mean_excess / std_excess * sqrt(periods_per_year)) if std_excess > 0.0 else 0.0
    te_val = std_excess * sqrt(periods_per_year) if std_excess > 0.0 else 0.0

    strat_return_val = _total_return(eq_s)
    excess_return_val = strat_return_val - bm_return_val

    excess_max_dd = _excess_max_drawdown(eq_s, eq_b)

    return BenchmarkCompareResult(
        benchmark_return=Decimal(str(bm_return_val)),
        benchmark_annualized_return=Decimal(str(bm_cagr)),
        benchmark_volatility=Decimal(str(bm_vol)),
        benchmark_max_drawdown=Decimal(str(bm_max_dd)),
        excess_return=Decimal(str(excess_return_val)),
        alpha=Decimal(str(alpha_val)),
        beta=Decimal(str(beta_val)),
        tracking_error=Decimal(str(te_val)),
        information_ratio=Decimal(str(ir_val)),
        excess_max_drawdown=Decimal(str(excess_max_dd)),
    )


# ---------------------------------------------------------------------------
# Benchmark data utilities
# ---------------------------------------------------------------------------


class Benchmark:
    """Utility for creating and validating benchmark equity curves."""

    @staticmethod
    def from_equity_curve(df: pl.DataFrame) -> pl.DataFrame:
        """Validate a benchmark equity curve and return it unchanged.

        Parameters
        ----------
        df : pl.DataFrame
            Must contain ``["dt", "equity"]`` columns, be non-empty, and
            contain no nulls in the ``equity`` column.

        Returns
        -------
        pl.DataFrame
            The validated DataFrame (pass-through).
        """
        _validate_equity_curve(df)
        return df

    @staticmethod
    def cash(
        initial_value: Decimal,
        annual_rate: Decimal,
        periods: int,
        *,
        start_dt: str | None = None,
    ) -> pl.DataFrame:
        """Generate a cash-benchmark equity curve compounding daily.

        Parameters
        ----------
        initial_value : Decimal
            Starting equity value.
        annual_rate : Decimal
            Annualized interest rate (e.g. ``Decimal("0.03")`` for 3%).
        periods : int
            Number of periods (bars) to generate.
        start_dt : str | None
            Optional ISO-format date string for the first period (e.g.
            ``"2026-01-01"``).  If ``None``, the ``dt`` column will be a
            zero-based integer index.

        Returns
        -------
        pl.DataFrame
            ``[dt, equity]`` with the cash compounding curve.
        """
        if initial_value <= _DECIMAL_ZERO:
            raise BenchmarkError("initial_value must be positive")
        if periods < 1:
            raise BenchmarkError("periods must be at least 1")

        daily_rate = float(annual_rate) / 252.0
        init = float(initial_value)

        equity_vals: list[float] = [init * (1.0 + daily_rate) ** i for i in range(periods)]

        if start_dt is not None:
            tz = get_shanghai_tz()
            base = datetime.fromisoformat(start_dt)
            if base.tzinfo is None:
                base = base.replace(tzinfo=tz)
            dts: list[datetime | int] = [base + timedelta(days=i) for i in range(periods)]
            dtype = pl.Datetime("ms", "Asia/Shanghai")
        else:
            dts = list(range(periods))
            dtype = pl.Int64

        return pl.DataFrame(
            {"dt": dts, "equity": equity_vals},
            schema_overrides={"dt": dtype, "equity": pl.Float64},
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_inputs(
    strategy_curve: pl.DataFrame,
    benchmark_curve: pl.DataFrame,
    periods_per_year: int,
) -> None:
    """Validate the inputs to ``compute_benchmark_comparison``."""
    if periods_per_year < 1:
        raise BenchmarkError("periods_per_year must be at least 1")
    _validate_equity_curve(strategy_curve, name="strategy")
    _validate_equity_curve(benchmark_curve, name="benchmark")


def _validate_equity_curve(df: pl.DataFrame, name: str = "benchmark") -> None:
    """Validate an equity curve DataFrame."""
    required = {"dt", "equity"}
    missing = required - set(df.columns)
    if missing:
        raise BenchmarkError(f"{name} equity curve missing columns: {', '.join(sorted(missing))}")
    if df.is_empty():
        raise BenchmarkError(f"{name} equity curve must not be empty")


def _returns(eq: np.ndarray) -> np.ndarray:
    """Compute daily returns from an equity curve."""
    return eq[1:] / eq[:-1] - 1.0


def _total_return(eq: np.ndarray) -> float:
    """Compute total return from an equity curve."""
    return float((eq[-1] - eq[0]) / eq[0])


def _cagr(eq: np.ndarray, periods_per_year: int, n_bars: int) -> float:
    """Compute compounded annual growth rate."""
    return float((eq[-1] / eq[0]) ** (periods_per_year / n_bars) - 1.0)


def _annualized_vol(returns: np.ndarray, periods_per_year: int) -> float:
    """Compute annualized volatility from daily returns."""
    if len(returns) < 2:
        return 0.0
    daily_vol = float(returns.std(ddof=1))
    return daily_vol * sqrt(periods_per_year)


def _max_drawdown(eq: np.ndarray) -> float:
    """Compute maximum drawdown (negative value)."""
    running_max = eq[0]
    max_dd = 0.0
    for v in eq[1:]:
        if v > running_max:
            running_max = v
        else:
            dd = (v - running_max) / running_max
            if dd < max_dd:
                max_dd = dd
    return max_dd


def _beta(r_s: np.ndarray, r_b: np.ndarray) -> float:
    """Compute beta: Cov(r_s, r_b) / Var(r_b)."""
    cov_mat = np.cov(r_s, r_b)
    if cov_mat[1, 1] > 0.0:
        return float(cov_mat[0, 1] / cov_mat[1, 1])
    return 0.0


def _excess_max_drawdown(eq_s: np.ndarray, eq_b: np.ndarray) -> float:
    """Compute max drawdown of the cumulative excess curve.

    Both curves are normalized to start at the same value (the strategy's
    initial equity) before computing the excess.
    """
    # Normalize benchmark to match strategy start
    scale = eq_s[0] / eq_b[0]
    excess_eq = eq_s - eq_b * scale

    running_max = excess_eq[0]
    max_dd = 0.0
    for v in excess_eq[1:]:
        if v > running_max:
            running_max = v
        dd = 0.0
        if running_max != 0.0:
            dd = (v - running_max) / abs(running_max)
        if dd < max_dd:
            max_dd = dd
    return max_dd
