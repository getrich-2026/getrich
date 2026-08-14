"""Trade journal and cost/PNL attribution for backtest results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import polars as pl
import statsmodels.api as sm

from getrich_backtest.calendar import (  # noqa: F401 (re-export via __init__.py)
    DEFAULT_ASHARE_SESSIONS,
    DEFAULT_FUTURES_SESSIONS,
    Session,
)
from getrich_backtest.execution import Fill
from getrich_backtest.types import Side


class AttributionError(ValueError):
    """Raised when attribution inputs are invalid."""


_DECIMAL_ZERO = Decimal("0")


def compute_trade_journal(fills: tuple[Fill, ...]) -> pl.DataFrame:
    """Build a structured trade journal from a sequence of fills.

    Each row is one fill with per-fill realized PnL recovered by simulating
    average-cost tracking per symbol.

    Parameters
    ----------
    fills : tuple[Fill, ...]
        Chronologically ordered fills (will be sorted by symbol then time).

    Returns
    -------
    pl.DataFrame
        Columns: ``fill_id``, ``order_id``, ``symbol``, ``side``, ``qty``,
        ``price``, ``notional``, ``fee``, ``slippage``, ``fill_time``,
        ``bar_dt``, ``strategy_name``, ``tag``, ``avg_cost_at_trade``,
        ``realized_pnl``, ``cumulative_realized_pnl``.

    Raises
    ------
    AttributionError
        If ``fills`` is empty.
    """
    if not fills:
        raise AttributionError("fills must not be empty")

    # Sort by symbol then fill_time for per-symbol cost tracking
    sorted_fills = sorted(fills, key=lambda f: (f.symbol, f.fill_time))

    rows: list[dict[str, object]] = []

    # Per-symbol running cost tracking
    cost_tracker: dict[str, dict[str, Decimal]] = {}

    for fill in sorted_fills:
        sym = fill.symbol
        if sym not in cost_tracker:
            cost_tracker[sym] = {"total_qty": _DECIMAL_ZERO, "total_cost": _DECIMAL_ZERO}

        tracker = cost_tracker[sym]
        avg_cost = (
            tracker["total_cost"] / tracker["total_qty"]
            if tracker["total_qty"] > _DECIMAL_ZERO
            else _DECIMAL_ZERO
        )
        realized_pnl: Decimal = _DECIMAL_ZERO

        if fill.side == Side.BUY:
            # Average cost: (existing_cost + new_cost) / (existing_qty + new_qty)
            new_qty = tracker["total_qty"] + fill.qty
            new_cost = tracker["total_cost"] + fill.notional
            tracker["total_qty"] = new_qty
            tracker["total_cost"] = new_cost
        elif fill.side == Side.SELL:
            # Realized PnL: (sell_price - avg_cost) * qty
            sell_qty = min(fill.qty, tracker["total_qty"])
            realized_pnl = (fill.price - avg_cost) * sell_qty
            tracker["total_qty"] -= sell_qty
            # Adjust total_cost proportionally
            if tracker["total_qty"] > _DECIMAL_ZERO:
                tracker["total_cost"] = avg_cost * tracker["total_qty"]
            else:
                tracker["total_cost"] = _DECIMAL_ZERO

        rows.append(
            {
                "fill_id": fill.fill_id,
                "order_id": fill.order_id,
                "symbol": fill.symbol,
                "side": fill.side.value,
                "qty": float(fill.qty),
                "price": float(fill.price),
                "notional": float(fill.notional),
                "fee": float(fill.fee),
                "slippage": float(fill.slippage),
                "fill_time": fill.fill_time,
                "bar_dt": fill.bar_dt,
                "strategy_name": fill.strategy_name,
                "tag": fill.tag,
                "avg_cost_at_trade": float(avg_cost),
                "realized_pnl": float(realized_pnl),
            }
        )

    df = pl.DataFrame(rows)

    # Compute cumulative realized PnL per symbol
    df = df.with_columns(
        pl.col("realized_pnl").cum_sum().over("symbol").alias("cumulative_realized_pnl")
    )

    return df


def compute_cost_attribution(fills: tuple[Fill, ...]) -> pl.DataFrame:
    """Aggregate trading costs by symbol.

    Parameters
    ----------
    fills : tuple[Fill, ...]
        Sequence of fills.

    Returns
    -------
    pl.DataFrame
        Columns: ``symbol``, ``total_notional``, ``total_fee``,
        ``total_slippage``, ``total_cost``, ``fee_rate_bps``,
        ``slippage_rate_bps``, ``n_fills``, sorted by ``total_cost``
        descending.

    Raises
    ------
    AttributionError
        If ``fills`` is empty.
    """
    if not fills:
        raise AttributionError("fills must not be empty")

    journal = compute_trade_journal(fills)
    return (
        journal.group_by("symbol")
        .agg(
            pl.col("notional").sum().alias("total_notional"),
            pl.col("fee").sum().alias("total_fee"),
            pl.col("slippage").sum().alias("total_slippage"),
            pl.len().alias("n_fills"),
        )
        .with_columns(
            (pl.col("total_fee") + pl.col("total_slippage")).alias("total_cost"),
        )
        .with_columns(
            (
                pl.when(pl.col("total_notional") > 0)
                .then(pl.col("total_fee") / pl.col("total_notional") * 10000)
                .otherwise(0.0)
            ).alias("fee_rate_bps"),
            (
                pl.when(pl.col("total_notional") > 0)
                .then(pl.col("total_slippage") / pl.col("total_notional") * 10000)
                .otherwise(0.0)
            ).alias("slippage_rate_bps"),
        )
        .sort("total_cost", descending=True)
    )


def compute_pnl_attribution(fills: tuple[Fill, ...]) -> pl.DataFrame:
    """Aggregate realized PnL by symbol.

    Uses the trade journal to compute net realized PnL (gross minus fees)
    per symbol.

    Parameters
    ----------
    fills : tuple[Fill, ...]
        Sequence of fills.

    Returns
    -------
    pl.DataFrame
        Columns: ``symbol``, ``total_realized_pnl``, ``total_fee``,
        ``net_pnl``, ``n_trades``, sorted by ``net_pnl`` descending.

    Raises
    ------
    AttributionError
        If ``fills`` is empty.
    """
    if not fills:
        raise AttributionError("fills must not be empty")

    journal = compute_trade_journal(fills)
    return (
        journal.group_by("symbol")
        .agg(
            pl.col("realized_pnl").sum().alias("total_realized_pnl"),
            pl.col("fee").sum().alias("total_fee"),
            (pl.col("side") == "SELL").sum().alias("n_trades"),
        )
        .with_columns(
            (pl.col("total_realized_pnl") - pl.col("total_fee")).alias("net_pnl"),
        )
        .sort("net_pnl", descending=True)
    )


def compute_brinson_attribution(
    trade_journal: pl.DataFrame,
    close_prices: pl.DataFrame,
    classifications: pl.DataFrame,
    benchmark_weights: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Compute Brinson industry attribution.

    Decomposes active return into allocation, selection, and interaction
    effects by industry.

    Parameters
    ----------
    trade_journal : pl.DataFrame
        Trade journal from ``compute_trade_journal()``. Must contain
        ``["symbol", "side", "qty", "bar_dt"]``.
    close_prices : pl.DataFrame
        Per-period close prices ``["dt", "symbol", "close"]``. Must be
        sorted by ``dt``.
    classifications : pl.DataFrame
        Symbol-to-industry mapping ``["symbol", "industry_l1"]``.
    benchmark_weights : pl.DataFrame | None
        Benchmark weights ``["dt", "symbol", "weight"]``. If ``None``,
        equal-weight all symbols that have close prices at each date.

    Returns
    -------
    pl.DataFrame
        Columns: ``dt``, ``industry``, ``portfolio_weight``,
        ``benchmark_weight``, ``portfolio_return``, ``benchmark_return``,
        ``allocation``, ``selection``, ``interaction``, ``active_return``.
        One row per industry per period.

    Raises
    ------
    AttributionError
        If inputs are invalid.
    """
    required_tj = {"symbol", "side", "qty", "bar_dt"}
    missing_tj = required_tj - set(trade_journal.columns)
    if missing_tj:
        raise AttributionError(f"trade_journal missing columns: {', '.join(sorted(missing_tj))}")
    required_cp = {"dt", "symbol", "close"}
    missing_cp = required_cp - set(close_prices.columns)
    if missing_cp:
        raise AttributionError(f"close_prices missing columns: {', '.join(sorted(missing_cp))}")
    required_cl = {"symbol", "industry_l1"}
    missing_cl = required_cl - set(classifications.columns)
    if missing_cl:
        raise AttributionError(f"classifications missing columns: {', '.join(sorted(missing_cl))}")

    dates = close_prices.select("dt").unique().sort("dt")
    if dates.height < 2:
        raise AttributionError("need at least 2 periods for return calculation")

    # Build qty deltas per period from trade journal
    qty_deltas = (
        trade_journal.with_columns(
            pl.when(pl.col("side") == "BUY")
            .then(pl.col("qty"))
            .when(pl.col("side") == "SELL")
            .then(-pl.col("qty"))
            .otherwise(0.0)
            .alias("delta"),
        )
        .group_by("bar_dt", "symbol")
        .agg(pl.col("delta").sum())
        .rename({"bar_dt": "dt"})
    )

    # Start from close_prices as the natural dt×symbol grid
    sym_industry = classifications.select("symbol", "industry_l1").unique().drop_nulls()
    # Ensure consistent datetime type for join
    if qty_deltas.height > 0 and qty_deltas["dt"].dtype != close_prices["dt"].dtype:
        qty_deltas = qty_deltas.with_columns(pl.col("dt").cast(close_prices["dt"].dtype))

    enriched = close_prices.join(qty_deltas, on=["dt", "symbol"], how="left")

    # Compute cumulative positions per symbol using global order
    enriched = (
        enriched.sort("dt", "symbol")
        .with_columns(
            pl.col("delta").fill_null(0.0),
        )
        .with_columns(
            pl.col("delta").cum_sum().over("symbol").alias("position"),
        )
    )

    # Add industry classification
    enriched = enriched.join(sym_industry, on="symbol", how="left")

    # Compute returns (close_t / close_{t-1} - 1)
    enriched = (
        enriched.with_columns(
            pl.col("close").shift(1).over("symbol").alias("close_prev"),
        )
        .with_columns(
            (pl.col("close") / pl.col("close_prev") - 1.0).alias("return"),
        )
        .filter(pl.col("close_prev").is_not_null())
    )

    if enriched.height == 0:
        raise AttributionError("no periods with valid returns after alignment")

    # Build benchmark weights: user-provided or equal-weight
    if benchmark_weights is not None:
        bm = benchmark_weights.rename(
            {"weight": "benchmark_weight", "dt": "bm_dt", "symbol": "bm_symbol"}
        )
        if bm.height > 0 and bm["bm_dt"].dtype != close_prices["dt"].dtype:
            bm = bm.with_columns(pl.col("bm_dt").cast(close_prices["dt"].dtype))
        enriched = enriched.join(
            bm,
            left_on=["dt", "symbol"],
            right_on=["bm_dt", "bm_symbol"],
            how="left",
        )
        # Fall back to equal-weight for symbols without benchmark weights
        enriched = enriched.with_columns(
            pl.col("benchmark_weight").fill_null(0.0),
        )
    else:
        # Equal-weight: each symbol gets 1/N per period
        enriched = enriched.with_columns(
            (1.0 / pl.col("symbol").count().over("dt")).alias("benchmark_weight"),
        )

    # Compute portfolio weights
    enriched = enriched.with_columns(
        (pl.col("position") * pl.col("close")).alias("market_value"),
    )

    # Per-period portfolio weight
    enriched = enriched.with_columns(
        (pl.col("market_value") / pl.col("market_value").sum().over("dt")).alias(
            "portfolio_weight",
        ),
    )

    # Drop symbols with null weights/industry
    enriched = enriched.filter(
        pl.col("portfolio_weight").is_not_null() & pl.col("industry_l1").is_not_null()
    )

    if enriched.height == 0:
        raise AttributionError("no valid data after computing weights")

    # Pre-compute weighted returns for clean aggregation
    enriched = enriched.with_columns(
        (pl.col("portfolio_weight") * pl.col("return")).alias("_port_wret"),
        (pl.col("benchmark_weight") * pl.col("return")).alias("_bm_wret"),
    )

    # Aggregate to industry level
    industry_level = (
        enriched.group_by("dt", "industry_l1", maintain_order=True)
        .agg(
            pl.col("portfolio_weight").sum(),
            pl.col("benchmark_weight").sum(),
            pl.col("_port_wret").sum(),
            pl.col("_bm_wret").sum(),
        )
        .sort("dt", "industry_l1")
    )

    # Compute weighted average returns
    industry_level = industry_level.with_columns(
        (pl.col("_port_wret") / pl.col("portfolio_weight")).alias("portfolio_return"),
        (pl.col("_bm_wret") / pl.col("benchmark_weight")).alias("benchmark_return"),
    )

    # Fill NaN returns (industry with zero weight)
    industry_level = industry_level.with_columns(
        pl.col("portfolio_return").fill_null(0.0),
        pl.col("benchmark_return").fill_null(0.0),
    )

    # Brinson decomposition
    industry_level = industry_level.with_columns(
        (
            (pl.col("portfolio_weight") - pl.col("benchmark_weight")) * pl.col("benchmark_return")
        ).alias("allocation"),
        (
            pl.col("benchmark_weight") * (pl.col("portfolio_return") - pl.col("benchmark_return"))
        ).alias("selection"),
        (
            (pl.col("portfolio_weight") - pl.col("benchmark_weight"))
            * (pl.col("portfolio_return") - pl.col("benchmark_return"))
        ).alias("interaction"),
    ).with_columns(
        (pl.col("allocation") + pl.col("selection") + pl.col("interaction")).alias(
            "active_return",
        ),
    )

    return industry_level.select(
        "dt",
        "industry_l1",
        "portfolio_weight",
        "benchmark_weight",
        "portfolio_return",
        "benchmark_return",
        "allocation",
        "selection",
        "interaction",
        "active_return",
    )


# ---------------------------------------------------------------------------
# Factor regression attribution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FactorExposure:
    """Per-factor exposure from factor regression."""

    name: str
    beta: Decimal
    t_stat: Decimal
    p_value: Decimal
    contribution_pnl: Decimal

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "beta": str(self.beta),
            "t_stat": str(self.t_stat),
            "p_value": str(self.p_value),
            "contribution_pnl": str(self.contribution_pnl),
        }


@dataclass(frozen=True)
class FactorRegResult:
    """Factor regression attribution result."""

    alpha: Decimal
    alpha_tstat: Decimal
    r_squared: Decimal
    adj_r_squared: Decimal
    n_periods: int
    factors: tuple[FactorExposure, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "alpha": str(self.alpha),
            "alpha_tstat": str(self.alpha_tstat),
            "r_squared": str(self.r_squared),
            "adj_r_squared": str(self.adj_r_squared),
            "n_periods": self.n_periods,
            "factors": [f.to_dict() for f in self.factors],
        }


def compute_factor_regression(
    equity_curve: pl.DataFrame,
    close_prices: pl.DataFrame,
    factors: dict[str, pl.DataFrame],
    factor_names: list[str],
    *,
    initial_cash: Decimal = Decimal("100000"),
    n_quantiles: int = 10,
) -> FactorRegResult:
    """Decompose strategy returns into factor exposures via OLS regression.

    For each factor, constructs a factor-mimicking portfolio return by
    going long the top quantile of stocks and short the bottom quantile
    (equal-weighted) at each period.  Strategy returns are then regressed
    against these factor returns.

    Parameters
    ----------
    equity_curve : pl.DataFrame
        Strategy equity curve with ``["dt", "equity"]`` columns, sorted by
        ``dt``.
    close_prices : pl.DataFrame
        Per-period close prices ``["dt", "symbol", "close"]``, sorted by
        ``dt``.
    factors : dict[str, pl.DataFrame]
        Map of factor name to DataFrame with ``["dt", "symbol", "value"]``
        columns.
    factor_names : list[str]
        Subset of factor names to include in the regression.
    initial_cash : Decimal
        Initial cash used to scale contribution PnL estimates.
    n_quantiles : int
        Number of quantiles for factor portfolio construction (default 10).

    Returns
    -------
    FactorRegResult

    Raises
    ------
    AttributionError
        If inputs are invalid.
    """
    if not factor_names:
        raise AttributionError("factor_names must not be empty")
    if n_quantiles < 2:
        raise AttributionError("n_quantiles must be at least 2")
    required_eq = {"dt", "equity"}
    missing_eq = required_eq - set(equity_curve.columns)
    if missing_eq:
        raise AttributionError(f"equity_curve missing columns: {', '.join(sorted(missing_eq))}")
    required_cp = {"dt", "symbol", "close"}
    missing_cp = required_cp - set(close_prices.columns)
    if missing_cp:
        raise AttributionError(f"close_prices missing columns: {', '.join(sorted(missing_cp))}")

    # Compute strategy returns
    strat_returns = _compute_strategy_returns(equity_curve)

    # Compute factor returns for each factor
    factor_return_dfs: list[pl.DataFrame] = []
    for name in factor_names:
        if name not in factors:
            raise AttributionError(f"factor '{name}' not found in factors dict")
        factor_df = factors[name]
        req_cols = {"dt", "symbol", "value"}
        missing = req_cols - set(factor_df.columns)
        if missing:
            raise AttributionError(
                f"factor '{name}' data missing columns: {', '.join(sorted(missing))}"
            )
        fr = _compute_factor_return(factor_df, close_prices, name, n_quantiles)
        factor_return_dfs.append(fr)

    if not factor_return_dfs:
        raise AttributionError("no factor returns could be computed")

    # Align all returns on common dates
    aligned = strat_returns
    for fr in factor_return_dfs:
        aligned = aligned.join(fr, on="dt", how="inner")

    if aligned.height < 3:
        raise AttributionError(
            f"need at least 3 aligned periods for regression (got {aligned.height})"
        )

    # Build regression matrix
    y = aligned["strategy_return"].to_numpy()
    factor_cols = [f"{name}_return" for name in factor_names]
    x = aligned.select(factor_cols).to_numpy()
    x = sm.add_constant(x)  # adds intercept column

    # OLS regression
    model = sm.OLS(y, x)
    results = model.fit()

    # Extract results
    alpha_float = float(results.params[0])
    alpha_tstat_float = float(results.tvalues[0])
    r_sq = float(results.rsquared)
    adj_r_sq = float(results.rsquared_adj)
    n_periods = aligned.height

    factors_list: list[FactorExposure] = []
    for i, name in enumerate(factor_names):
        beta_float = float(results.params[i + 1])
        t_stat_float = float(results.tvalues[i + 1])
        p_val_float = float(results.pvalues[i + 1])
        mean_fret = float(aligned[f"{name}_return"].mean())
        contribution = beta_float * mean_fret * n_periods * float(initial_cash)

        factors_list.append(
            FactorExposure(
                name=name,
                beta=Decimal(str(beta_float)),
                t_stat=Decimal(str(t_stat_float)),
                p_value=Decimal(str(p_val_float)),
                contribution_pnl=Decimal(str(contribution)),
            )
        )

    return FactorRegResult(
        alpha=Decimal(str(alpha_float)),
        alpha_tstat=Decimal(str(alpha_tstat_float)),
        r_squared=Decimal(str(r_sq)),
        adj_r_squared=Decimal(str(adj_r_sq)),
        n_periods=n_periods,
        factors=tuple(factors_list),
    )


# ---------------------------------------------------------------------------
# Factor regression internal helpers
# ---------------------------------------------------------------------------


def _compute_strategy_returns(equity_curve: pl.DataFrame) -> pl.DataFrame:
    """Compute per-period strategy returns from an equity curve."""
    return equity_curve.select(
        "dt",
        (pl.col("equity") / pl.col("equity").shift(1) - 1.0).alias("strategy_return"),
    ).filter(pl.col("strategy_return").is_not_null())


def _compute_factor_return(
    factor_df: pl.DataFrame,
    close_prices: pl.DataFrame,
    factor_name: str,
    n_quantiles: int,
) -> pl.DataFrame:
    """Compute factor-mimicking portfolio return time series.

    On each date, ranks symbols by factor value, assigns to quantiles,
    and computes the equal-weighted return of the top quantile minus
    the bottom quantile.
    """
    # Merge factor values with close prices to get returns
    factor_with_close = factor_df.join(close_prices, on=["dt", "symbol"], how="inner").sort(
        "dt", "symbol"
    )

    # Compute per-symbol returns
    factor_with_close = (
        factor_with_close.with_columns(
            pl.col("close").shift(1).over("symbol").alias("close_prev"),
        )
        .with_columns(
            (pl.col("close") / pl.col("close_prev") - 1.0).alias("return"),
        )
        .filter(pl.col("close_prev").is_not_null())
    )

    if factor_with_close.height == 0:
        raise AttributionError(
            f"factor '{factor_name}' has no valid data after aligning with close prices"
        )

    # Rank and assign quantiles
    n_sym_per_dt = pl.len().over("dt")
    factor_with_close = factor_with_close.with_columns(
        pl.col("value").rank("ordinal").over("dt").alias("rank"),
    ).with_columns(
        # Quantile label: 0 = bottom, n_quantiles-1 = top
        # Using n_quantiles (not n_quantiles-1) so the full range is populated.
        ((pl.col("rank") - 1) * n_quantiles / n_sym_per_dt)
        .floor()
        .cast(pl.Int32)
        .clip(0, n_quantiles - 1)
        .alias("quantile"),
    )

    # Compute equal-weighted return per quantile per dt
    quantile_returns = factor_with_close.group_by("dt", "quantile").agg(
        pl.col("return").mean().alias("q_return"),
    )

    # Factor return = top quantile return - bottom quantile return
    top = quantile_returns.filter(pl.col("quantile") == n_quantiles - 1).select(
        "dt", pl.col("q_return").alias("top_return")
    )
    bottom = quantile_returns.filter(pl.col("quantile") == 0).select(
        "dt", pl.col("q_return").alias("bottom_return")
    )

    factor_return = (
        top.join(bottom, on="dt", how="inner")
        .with_columns(
            (pl.col("top_return") - pl.col("bottom_return")).alias(f"{factor_name}_return"),
        )
        .select("dt", f"{factor_name}_return")
    )

    return factor_return


# ---------------------------------------------------------------------------
# Session attribution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionStats:
    """Aggregated return statistics for one trading session."""

    name: str
    count: int
    total_return: Decimal
    mean_return: Decimal
    std_return: Decimal
    sharpe: Decimal
    win_rate: Decimal
    contribution_pnl: Decimal

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "count": self.count,
            "total_return": str(self.total_return),
            "mean_return": str(self.mean_return),
            "std_return": str(self.std_return),
            "sharpe": str(self.sharpe),
            "win_rate": str(self.win_rate),
            "contribution_pnl": str(self.contribution_pnl),
        }


@dataclass(frozen=True)
class SessionAttributionResult:
    """Collection of per-session return attribution."""

    sessions: tuple[SessionStats, ...]
    total_periods: int
    unclassified_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "sessions": [s.to_dict() for s in self.sessions],
            "total_periods": self.total_periods,
            "unclassified_count": self.unclassified_count,
        }


_SHARPE_CAP = Decimal("99")


def _classify_session(dt: datetime, sessions: tuple[Session, ...]) -> str | None:
    """Classify a datetime into a named session, or ``None``."""
    t = dt.hour * 60 + dt.minute
    for sess in sessions:
        start = sess.start_hour * 60 + sess.start_minute
        end = sess.end_hour * 60 + sess.end_minute
        if sess.spans_midnight:
            if t >= start or t < end:
                return sess.name
        else:
            if start <= t < end:
                return sess.name
    return None


def compute_session_attribution(
    equity_curve: pl.DataFrame,
    sessions: tuple[Session, ...] = DEFAULT_FUTURES_SESSIONS,
    *,
    initial_cash: Decimal = Decimal("100000"),
) -> SessionAttributionResult:
    """Decompose strategy returns by trading session.

    For each period in the equity curve, computes the per-period return
    and classifies it into a trading session based on the timestamp's
    time-of-day.  Statistics (count, total/mean/std return, Sharpe,
    win-rate, contribution PnL) are then aggregated per session.

    Parameters
    ----------
    equity_curve : pl.DataFrame
        Strategy equity curve with ``["dt", "equity"]`` columns, sorted
        by ``dt``.  ``dt`` must be timezone-aware (Asia/Shanghai).
    sessions : tuple[Session, ...]
        Session definitions.  Defaults to ``DEFAULT_FUTURES_SESSIONS``
        (night/morning/afternoon).
    initial_cash : Decimal
        Initial cash, used for scaling contribution PnL.

    Returns
    -------
    SessionAttributionResult

    Raises
    ------
    AttributionError
        If inputs are invalid.
    """
    required = {"dt", "equity"}
    missing = required - set(equity_curve.columns)
    if missing:
        raise AttributionError(f"equity_curve missing columns: {', '.join(sorted(missing))}")
    if equity_curve.height < 2:
        raise AttributionError(
            f"equity_curve must have at least 2 rows (got {equity_curve.height})"
        )

    # Compute per-period strategy returns
    strat_returns = _compute_strategy_returns(equity_curve)

    # Compute per-period dollar PnL
    dollar_pnl = equity_curve.select(
        "dt",
        (pl.col("equity") - pl.col("equity").shift(1)).alias("dollar_pnl"),
    ).filter(pl.col("dollar_pnl").is_not_null())

    # Classify each period by session
    classified = strat_returns.with_columns(
        pl.struct("dt")
        .map_elements(
            lambda row: _classify_session(row["dt"], sessions),
            return_dtype=pl.String,
        )
        .alias("session"),
    )

    # Join with dollar PnL
    classified = classified.join(dollar_pnl, on="dt", how="inner")

    # Separate classified and unclassified
    known = classified.filter(pl.col("session").is_not_null())
    unclassified = classified.filter(pl.col("session").is_null()).height

    if known.height == 0:
        raise AttributionError("no periods could be classified into any session")

    # Aggregate per session
    grouped = (
        known.group_by("session")
        .agg(
            pl.len().alias("count"),
            pl.col("strategy_return").sum().alias("total_return"),
            pl.col("strategy_return").mean().alias("mean_return"),
            pl.col("strategy_return").std().alias("std_return"),
            (pl.col("strategy_return") > 0).mean().alias("win_rate"),
            pl.col("dollar_pnl").sum().alias("contribution_pnl"),
        )
        .sort("session")
    )

    # Replace NaN std with 0 (happens when a session has only 1 bar)
    grouped = grouped.with_columns(
        pl.col("std_return").fill_nan(0.0).fill_null(0.0),
    )

    # Build SessionStats objects
    stats_list: list[SessionStats] = []
    for row in grouped.iter_rows(named=True):
        mean_r = Decimal(str(row["mean_return"]))
        std_r = Decimal(str(row["std_return"]))
        if std_r > _DECIMAL_ZERO:
            sharpe_val = mean_r / std_r
            if sharpe_val > _SHARPE_CAP:
                sharpe_val = _SHARPE_CAP
        else:
            sharpe_val = Decimal("0")

        stats_list.append(
            SessionStats(
                name=str(row["session"]),
                count=int(row["count"]),
                total_return=Decimal(str(row["total_return"])),
                mean_return=mean_r,
                std_return=std_r,
                sharpe=sharpe_val,
                win_rate=Decimal(str(row["win_rate"])),
                contribution_pnl=Decimal(str(row["contribution_pnl"])),
            )
        )

    return SessionAttributionResult(
        sessions=tuple(stats_list),
        total_periods=strat_returns.height,
        unclassified_count=unclassified,
    )
