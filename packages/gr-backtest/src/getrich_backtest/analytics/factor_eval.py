"""Factor evaluation metrics: IC, Rank IC, quantile portfolio returns.

All functions operate on Polars DataFrames and Series.  They are designed
for post-run analysis, independent of the backtest execution loop.
"""

from __future__ import annotations

import numpy as np
import polars as pl
from scipy.stats import spearmanr


def compute_ic(
    factor_scores: pl.Series,
    forward_returns: pl.Series,
    method: str = "spearman",
) -> float:
    """Compute Information Coefficient between factor scores and forward returns.

    Parameters
    ----------
    factor_scores : pl.Series
        Cross-sectional factor scores at a point in time.
    forward_returns : pl.Series
        Forward returns for the same symbols.
    method : {"spearman", "pearson"}
        Correlation method (default "spearman" — rank-based, robust to outliers).

    Returns
    -------
    float
        Correlation coefficient.  NaN if either series has fewer than 2 values.
    """
    if len(factor_scores) < 2 or len(forward_returns) < 2:
        return float("nan")

    f = factor_scores.to_numpy().flatten()
    r = forward_returns.to_numpy().flatten()

    valid = ~(np.isnan(f) | np.isnan(r))
    if valid.sum() < 2:
        return float("nan")

    f = f[valid]
    r = r[valid]

    if method == "spearman":
        corr, _ = spearmanr(f, r)
        return float(corr)
    else:
        corr = np.corrcoef(f, r)[0, 1]
        return float(corr if not np.isnan(corr) else float("nan"))


def compute_rank_ic(
    factor_scores: pl.Series,
    forward_returns: pl.Series,
) -> float:
    """Spearman rank IC (alias for ``compute_ic`` with ``method="spearman"``)."""
    return compute_ic(factor_scores, forward_returns, method="spearman")


def factor_evaluation_report(
    scores: pl.DataFrame,
    forward_returns: pl.DataFrame,
    n_quantiles: int = 10,
) -> pl.DataFrame:
    """Compute a factor evaluation report.

    The report contains per-period IC, cumulative IC, and quantile portfolio
    forward returns.

    Parameters
    ----------
    scores : pl.DataFrame
        Long-format factor scores with columns ``["dt", "symbol", "score"]``.
    forward_returns : pl.DataFrame
        Long-format forward returns with columns ``["dt", "symbol", "fwd_ret"]``.
        ``dt`` must align with the ``scores`` DataFrame so that each bar's
        scores can be matched to the corresponding forward returns.
    n_quantiles : int
        Number of quantile portfolios to form (default 10).

    Returns
    -------
    pl.DataFrame
        Columns: ``dt``, ``ic``, ``rank_ic``, ``quantile_{1..n}``, ``long_short``.
    """
    _validate_report_inputs(scores, forward_returns)

    # Merge scores with forward returns
    merged = scores.join(forward_returns, on=["dt", "symbol"], how="inner")
    if merged.is_empty():
        return pl.DataFrame(
            {"dt": [], "ic": [], "rank_ic": []},
            schema={
                "dt": pl.Datetime("ms", "Asia/Shanghai"),
                "ic": pl.Float64,
                "rank_ic": pl.Float64,
            },
        )

    results: list[dict] = []

    for dt in merged["dt"].unique().sort():
        bar_data = merged.filter(pl.col("dt") == dt)
        if bar_data.height < n_quantiles * 2:
            continue

        score_vals = bar_data["score"]
        ret_vals = bar_data["fwd_ret"]

        # Per-bar IC
        ic = compute_ic(score_vals, ret_vals, method="pearson")
        rank_ic = compute_ic(score_vals, ret_vals, method="spearman")

        # Quantile portfolios
        bar_data = bar_data.with_columns(pl.col("score").rank("ordinal").over("dt").alias("rank"))
        total = bar_data.height
        # Assign to quantile (0-indexed)
        bar_data = bar_data.with_columns(
            (pl.col("rank") * n_quantiles // (total + 1)).clip(0, n_quantiles - 1).alias("quantile")
        )

        q_returns: dict[str, float] = {}
        for q in range(n_quantiles):
            q_data = bar_data.filter(pl.col("quantile") == q)
            if q_data.height > 0:
                q_returns[f"quantile_{q + 1}"] = float(q_data["fwd_ret"].mean())
            else:
                q_returns[f"quantile_{q + 1}"] = 0.0

        # Long-short spread (top quantile - bottom quantile)
        long_short = q_returns.get(f"quantile_{n_quantiles}", 0.0) - q_returns.get(
            "quantile_1", 0.0
        )

        row: dict = {
            "dt": dt,
            "ic": ic,
            "rank_ic": rank_ic,
            **q_returns,
            "long_short": long_short,
        }
        results.append(row)

    if not results:
        return pl.DataFrame(
            {"dt": [], "ic": [], "rank_ic": []},
            schema={
                "dt": pl.Datetime("ms", "Asia/Shanghai"),
                "ic": pl.Float64,
                "rank_ic": pl.Float64,
            },
        )

    return pl.DataFrame(results)


def _validate_report_inputs(scores: pl.DataFrame, forward_returns: pl.DataFrame) -> None:
    """Validate inputs to ``factor_evaluation_report``."""
    from getrich_backtest.exceptions import StrategyError

    for name, required in [
        ("scores", {"dt", "symbol", "score"}),
        ("forward_returns", {"dt", "symbol", "fwd_ret"}),
    ]:
        missing = required.difference(
            scores.columns if name == "scores" else forward_returns.columns
        )
        if missing:
            raise StrategyError(f"{name} missing required columns: {', '.join(sorted(missing))}")


__all__ = [
    "compute_ic",
    "compute_rank_ic",
    "factor_evaluation_report",
]
