"""Factor evaluation and performance analytics.

This module provides post-hoc analysis tools for evaluating factor signals
and strategy performance.  Full implementations will be added in a future
phase; stub exports are provided to resolve the ``__init__.py`` import chain.
"""

from __future__ import annotations

import polars as pl

from getrich_backtest.exceptions import MetricsError


def compute_ic(
    factor: pl.DataFrame,
    forward_return: pl.DataFrame,
    method: str = "spearman",
) -> pl.DataFrame:
    """Compute Information Coefficient between factor and forward return.

    Parameters
    ----------
    factor : pl.DataFrame
        ``[dt, symbol, value]`` long table of factor exposures.
    forward_return : pl.DataFrame
        ``[dt, symbol, return]`` long table of forward returns.
    method : str
        Correlation method: ``"spearman"`` or ``"pearson"``.

    Returns
    -------
    pl.DataFrame
        ``[dt, ic, rank_ic]`` — one row per date.

    Raises
    ------
    MetricsError
        If inputs are empty or missing required columns.
    """
    _validate_factor_inputs(factor, forward_return)
    merged = factor.join(forward_return, on=["dt", "symbol"], how="inner")
    if merged.is_empty():
        raise MetricsError("no overlapping (dt, symbol) pairs between factor and forward_return")

    if method == "spearman":
        ic_expr = pl.corr(pl.col("value"), pl.col("return"), method="spearman")
    else:
        ic_expr = pl.corr(pl.col("value"), pl.col("return"))

    return merged.group_by("dt").agg(ic_expr.alias("ic")).sort("dt")


def compute_rank_ic(
    factor: pl.DataFrame,
    forward_return: pl.DataFrame,
) -> pl.DataFrame:
    """Convenience wrapper around ``compute_ic(method='spearman')``."""
    return compute_ic(factor, forward_return, method="spearman")


def factor_evaluation_report(
    factor: pl.DataFrame,
    forward_return: pl.DataFrame,
    n_quantiles: int = 5,
) -> pl.DataFrame:
    """Compute a quantile-based factor evaluation report.

    Parameters
    ----------
    factor : pl.DataFrame
        ``[dt, symbol, value]`` long table of factor exposures.
    forward_return : pl.DataFrame
        ``[dt, symbol, return]`` long table of forward returns.
    n_quantiles : int
        Number of quantiles (default 5 = quintiles).

    Returns
    -------
    pl.DataFrame
        ``[quantile, mean_return, mean_factor]`` — one row per quantile.
    """
    _validate_factor_inputs(factor, forward_return)
    merged = factor.join(forward_return, on=["dt", "symbol"], how="inner")
    if merged.is_empty():
        raise MetricsError("no overlapping (dt, symbol) pairs between factor and forward_return")

    return (
        merged.with_columns(
            pl.col("value").qcut(n_quantiles, labels=False).over("dt").alias("quantile")
        )
        .group_by("quantile")
        .agg(
            pl.col("return").mean().alias("mean_return"),
            pl.col("value").mean().alias("mean_factor"),
        )
        .sort("quantile")
    )


def _validate_factor_inputs(factor: pl.DataFrame, forward_return: pl.DataFrame) -> None:
    """Validate that both DataFrames have the expected columns."""
    checks: list[tuple[pl.DataFrame, str, list[str]]] = [
        (factor, "factor", ["dt", "symbol", "value"]),
        (forward_return, "forward_return", ["dt", "symbol", "return"]),
    ]
    for df, label, cols in checks:
        missing = [c for c in cols if c not in df.columns]
        if missing:
            raise MetricsError(f"{label} missing columns: {', '.join(missing)}")
        if df.is_empty():
            raise MetricsError(f"{label} must not be empty")
