"""Backtest performance metrics computation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import log, sqrt

import polars as pl

from gr_backtest.exceptions import MetricsError
from gr_backtest.result import BacktestResult


_DECIMAL_ZERO = Decimal("0")


@dataclass(frozen=True)
class BacktestMetrics:
    """Aggregated performance metrics from a backtest result."""

    strategy_name: str
    run_id: str

    # Raw returns
    total_return: Decimal
    log_return: Decimal

    # Risk-adjusted
    annualized_return: Decimal
    annualized_volatility: Decimal
    sharpe_ratio: Decimal
    sortino_ratio: Decimal
    calmar_ratio: Decimal

    # Drawdown
    max_drawdown: Decimal
    max_drawdown_duration: int

    # Activity
    total_fees: Decimal
    total_turnover: Decimal
    turnover_rate: Decimal
    total_trades: int

    # Metadata
    n_bars: int
    risk_free_rate: Decimal
    trading_days_per_year: int

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable dict (Decimal fields → str)."""
        return {
            "total_return": str(self.total_return),
            "log_return": str(self.log_return),
            "annualized_return": str(self.annualized_return),
            "annualized_volatility": str(self.annualized_volatility),
            "sharpe_ratio": str(self.sharpe_ratio),
            "sortino_ratio": str(self.sortino_ratio),
            "calmar_ratio": str(self.calmar_ratio),
            "max_drawdown": str(self.max_drawdown),
            "max_drawdown_duration": self.max_drawdown_duration,
            "total_fees": str(self.total_fees),
            "total_turnover": str(self.total_turnover),
            "turnover_rate": str(self.turnover_rate),
            "total_trades": self.total_trades,
            "n_bars": self.n_bars,
            "risk_free_rate": str(self.risk_free_rate),
            "trading_days_per_year": self.trading_days_per_year,
        }


def _to_daily_equity(equity_curve: pl.DataFrame) -> pl.DataFrame:
    """Downsample an equity curve to daily frequency.

    Groups by date and takes the last equity value per day. This ensures
    annualized metrics are computed from daily returns regardless of the
    original bar frequency.
    """
    return (
        equity_curve.with_columns(pl.col("dt").dt.date().alias("_date"))
        .sort(["dt"])
        .group_by("_date", maintain_order=True)
        .agg(pl.col("equity").last())
        .drop("_date")
    )


def compute_metrics(
    result: BacktestResult,
    *,
    equity_curve_override: pl.DataFrame | None = None,
    risk_free_rate: Decimal = Decimal("0.03"),
    trading_days_per_year: int = 252,
) -> BacktestMetrics:
    """Compute a minimal set of performance metrics from a backtest result.

    Parameters
    ----------
    result : BacktestResult
        A completed backtest result with equity_curve and fills.
    risk_free_rate : Decimal
        Annualized risk-free rate used for Sharpe ratio (default 3%).
    trading_days_per_year : int
        Number of trading periods per year for annualization (default 252).

    Returns
    -------
    BacktestMetrics
        Aggregated performance metrics.

    Raises
    ------
    MetricsError
        If the result data is degenerate (empty equity curve, zero initial
        cash, etc.).
    """
    _validate_inputs(result, trading_days_per_year)

    equity_curve = (
        equity_curve_override if equity_curve_override is not None else result.equity_curve
    )
    initial_cash = float(result.initial_cash)
    n_bars = equity_curve.height

    # Original (possibly sub-daily) equity for drawdown tracking
    equity = equity_curve["equity"].to_numpy().astype("float64")
    final_equity = float(equity[-1])

    total_return = (final_equity - initial_cash) / initial_cash
    log_return_val = log(1.0 + total_return)

    # Downsample to daily for frequency-independent annualization
    daily_eq = _to_daily_equity(equity_curve)
    daily_equity_array = daily_eq["equity"].to_numpy().astype("float64")
    n_daily = daily_eq.height

    # CAGR from daily data
    if n_daily >= 2:
        cagr = (final_equity / initial_cash) ** (trading_days_per_year / n_daily) - 1.0
    else:
        cagr = total_return  # single-day backtest: CAGR = total return

    daily_returns = (daily_equity_array[1:] / daily_equity_array[:-1]) - 1.0

    if len(daily_returns) < 2:
        annualized_vol = 0.0
    else:
        daily_vol = float(daily_returns.std(ddof=1))
        annualized_vol = daily_vol * sqrt(trading_days_per_year)

    sharpe = (cagr - float(risk_free_rate)) / annualized_vol if annualized_vol > 0.0 else 0.0

    # Sortino ratio — downside deviation only (from daily returns)
    if len(daily_returns) >= 2:
        neg_returns = daily_returns[daily_returns < 0.0]
        downside_std = float(neg_returns.std(ddof=1)) if len(neg_returns) > 0 else 0.0
        downside_vol = downside_std * sqrt(trading_days_per_year)
        sortino = (cagr - float(risk_free_rate)) / downside_vol if downside_vol > 0.0 else 99.0
    else:
        sortino = 0.0

    # Max drawdown — use original high-frequency equity for accuracy
    running_max = equity[0]
    max_dd = 0.0
    max_dd_duration = 0
    current_dd_start = 0

    for i in range(1, n_bars):
        if equity[i] > running_max:
            running_max = equity[i]
            current_dd_start = i
        else:
            dd = (equity[i] - running_max) / running_max
            if dd < max_dd:
                max_dd = dd
                max_dd_duration = i - current_dd_start

    # Calmar ratio — daily CAGR over max drawdown from original bars
    calmar = cagr / abs(max_dd) if max_dd < 0.0 else 0.0

    total_fees = _DECIMAL_ZERO
    total_turnover = _DECIMAL_ZERO
    for fill in result.fills:
        total_fees += fill.fee
        total_turnover += abs(fill.notional)

    mean_equity = float(equity.mean())
    turnover_rate_val = float(total_turnover) / mean_equity if mean_equity > 0.0 else 0.0

    return BacktestMetrics(
        strategy_name=result.strategy_name,
        run_id=result.run_id,
        total_return=Decimal(str(total_return)),
        log_return=Decimal(str(log_return_val)),
        annualized_return=Decimal(str(cagr)),
        annualized_volatility=Decimal(str(annualized_vol)),
        sharpe_ratio=Decimal(str(sharpe)),
        sortino_ratio=Decimal(str(sortino)),
        calmar_ratio=Decimal(str(calmar)),
        max_drawdown=Decimal(str(max_dd)),
        max_drawdown_duration=max_dd_duration,
        total_fees=total_fees,
        total_turnover=total_turnover,
        turnover_rate=Decimal(str(turnover_rate_val)),
        total_trades=len(result.fills),
        n_bars=n_bars,
        risk_free_rate=risk_free_rate,
        trading_days_per_year=trading_days_per_year,
    )


def _validate_inputs(result: BacktestResult, trading_days_per_year: int) -> None:
    if result.equity_curve.height < 2:
        raise MetricsError("equity_curve must have at least 2 rows")
    if result.initial_cash <= _DECIMAL_ZERO:
        raise MetricsError("initial_cash must be positive")
    if not result.strategy_name.strip():
        raise MetricsError("strategy_name must be non-empty")
    if trading_days_per_year < 1:
        raise MetricsError("trading_days_per_year must be at least 1")


def monthly_returns_heatmap(equity_curve: pl.DataFrame) -> pl.DataFrame:
    """Compute a year × month return matrix from an equity curve.

    Parameters
    ----------
    equity_curve : pl.DataFrame
        Must contain ``["dt", "equity"]`` columns sorted by ``dt``.

    Returns
    -------
    pl.DataFrame
        ``[year, month, return]`` — one row per calendar month present in
        the data.  Returns are computed as ``(equity_end / equity_start - 1)``
        within each month.
    """
    required = ["dt", "equity"]
    missing = [c for c in required if c not in equity_curve.columns]
    if missing:
        raise MetricsError(f"equity_curve missing columns: {', '.join(missing)}")

    if equity_curve.is_empty():
        raise MetricsError("equity_curve must not be empty")

    return (
        equity_curve.with_columns(
            pl.col("dt").dt.year().alias("year"),
            pl.col("dt").dt.month().alias("month"),
        )
        .group_by(["year", "month"], maintain_order=True)
        .agg(
            pl.col("equity").last().alias("end_equity"),
            pl.col("equity").first().alias("start_equity"),
        )
        .with_columns(((pl.col("end_equity") / pl.col("start_equity")) - 1.0).alias("return"))
        .select(["year", "month", "return"])
        .sort(["year", "month"])
    )
