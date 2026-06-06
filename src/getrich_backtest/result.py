"""Backtest result containers."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

import polars as pl

from getrich_backtest.execution import Fill, Order
from getrich_backtest.runconfig import RunConfig
from getrich_backtest.strategy.context import AccountView


if TYPE_CHECKING:
    from getrich_backtest.metrics import BacktestMetrics


_DECIMAL_ZERO = Decimal("0")


@dataclass(frozen=True)
class BacktestResult:
    """Minimal result returned by a completed backtest run."""

    run_id: str
    strategy_name: str
    initial_cash: Decimal
    config: RunConfig
    orders: tuple[Order, ...]
    fills: tuple[Fill, ...]
    final_account: AccountView
    equity_curve: pl.DataFrame = field(repr=False)
    benchmark_equity_curve: pl.DataFrame | None = field(default=None, repr=False)
    bars: pl.DataFrame | None = field(default=None, repr=False)
    extra_bars: dict[str, pl.DataFrame] | None = field(default=None, repr=False)
    sub_account_equity: dict[str, pl.DataFrame] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must be non-empty")
        if not self.strategy_name.strip():
            raise ValueError("strategy_name must be non-empty")
        if not isinstance(self.initial_cash, Decimal):
            raise ValueError("initial_cash must be decimal.Decimal")
        if self.initial_cash < _DECIMAL_ZERO:
            raise ValueError("initial_cash must be non-negative")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable summary dict.

        Decimal values are converted to ``str`` to preserve precision.
        Orders, fills and equity curve data are excluded — use the dedicated
        Parquet export for those.
        """
        d: dict[str, object] = {
            "run_id": self.run_id,
            "strategy_name": self.strategy_name,
            "fingerprint": self.config.fingerprint(),
            "config": self.config.to_dict(),
            "summary": {
                "initial_cash": str(self.initial_cash),
                "final_cash": str(self.final_account.cash),
                "final_equity": str(
                    self.equity_curve["equity"][-1]
                    if self.equity_curve.height > 0
                    else self.final_account.cash
                ),
            },
        }
        if self.benchmark_equity_curve is not None and self.benchmark_equity_curve.height > 0:
            d["summary"]["benchmark_final_equity"] = str(self.benchmark_equity_curve["equity"][-1])
        return d


# ---------------------------------------------------------------------------
# Multi-strategy result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CombinedResult(BacktestResult):
    """Multi-strategy backtest result with per-strategy views.

    Extends ``BacktestResult`` for backward compatibility.  Provides
    ``.strategy(name)`` and ``.combined`` accessors returning ``ResultView``.
    """

    _per_strategy_results: dict[str, BacktestResult] = field(default_factory=dict, repr=False)

    def strategy(self, name: str) -> ResultView:
        """Return a ``ResultView`` filtered to one strategy's data."""
        if name not in self._per_strategy_results:
            raise KeyError(
                f"strategy '{name}' not found. Available: {list(self._per_strategy_results)}"
            )
        return ResultView(self._per_strategy_results[name], name)

    @property
    def combined(self) -> ResultView:
        """Return a ``ResultView`` for the aggregated multi-strategy result."""
        return ResultView(self, "_combined")


@dataclass(frozen=True)
class ResultView:
    """Filtered projection of a backtest result for one strategy.

    Wraps a ``BacktestResult`` and provides strategy-scoped access to
    equity curve, fills, orders, and final account.
    """

    result: BacktestResult
    strategy_name: str

    @property
    def equity_curve(self) -> pl.DataFrame:
        ec = self.result.equity_curve
        if self.strategy_name == "_combined" or "strategy_name" not in ec.columns:
            return ec
        return ec.filter(pl.col("strategy_name") == self.strategy_name)

    @property
    def fills(self) -> tuple[Fill, ...]:
        if self.strategy_name == "_combined":
            return self.result.fills
        return tuple(f for f in self.result.fills if f.strategy_name == self.strategy_name)

    @property
    def orders(self) -> tuple[Order, ...]:
        if self.strategy_name == "_combined":
            return self.result.orders
        return tuple(o for o in self.result.orders if o.strategy_name == self.strategy_name)

    @property
    def initial_cash(self) -> Decimal:
        return self.result.initial_cash

    @property
    def final_account(self) -> AccountView:
        return self.result.final_account

    @property
    def run_id(self) -> str:
        return self.result.run_id

    @property
    def config(self) -> RunConfig:
        return self.result.config

    @property
    def benchmark_equity_curve(self) -> pl.DataFrame | None:
        """Return the benchmark equity curve, if any."""
        return self.result.benchmark_equity_curve

    def metrics(
        self,
        risk_free_rate: Decimal = Decimal("0.03"),
        trading_days_per_year: int = 252,
    ) -> BacktestMetrics:
        from getrich_backtest.metrics import compute_metrics

        """Compute metrics for this strategy view."""
        ec = self.equity_curve
        if self.strategy_name == "_combined" and "strategy_name" in ec.columns:
            # Aggregate per-bar before computing metrics
            ec = ec.group_by("dt", maintain_order=True).agg(
                pl.col("cash").sum(),
                pl.col("equity").sum(),
                pl.col("trading_pnl").sum(),
                pl.col("mtm_pnl").sum(),
                pl.col("total_fees").sum(),
                pl.col("gross_exposure").sum(),
            )
        return compute_metrics(
            result=self.result,
            equity_curve_override=ec,
            risk_free_rate=risk_free_rate,
            trading_days_per_year=trading_days_per_year,
        )

    def tear_sheet(self) -> None:
        """Print a human-readable performance summary."""

        m = self.metrics()
        print(f"=== {self.strategy_name} ===")
        print(f"  Total Return:      {m.total_return:.2%}")
        print(f"  Log Return:        {m.log_return:.2%}")
        print(f"  Annualized Return: {m.annualized_return:.2%}")
        print(f"  Volatility:        {m.annualized_volatility:.2%}")
        print(f"  Sharpe Ratio:      {m.sharpe_ratio:.3f}")
        print(f"  Max Drawdown:      {m.max_drawdown:.2%}")
        print(f"  Total Fees:        {m.total_fees}")
        print(f"  Total Trades:      {m.total_trades}")
