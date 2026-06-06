"""Analytics and factor evaluation modules for post-run analysis."""

from getrich_backtest.analytics.factor_eval import (
    compute_ic,
    compute_rank_ic,
    factor_evaluation_report,
)


__all__ = [
    "compute_ic",
    "compute_rank_ic",
    "factor_evaluation_report",
]
