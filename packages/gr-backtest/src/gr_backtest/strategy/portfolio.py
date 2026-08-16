"""Portfolio construction layer: signal → weight → OrderIntent.

Translates strategy signals into concrete orders via allocation,
constraints, and rebalance rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

import polars as pl

from gr_backtest.exceptions import StrategyError
from gr_backtest.strategy.context import BarContext
from gr_backtest.strategy.order import OrderIntent
from gr_backtest.strategy.preprocessor import SignalPreprocessor
from gr_backtest.types import OrderType, Side


_DECIMAL_ZERO = Decimal("0")
_EMPTY_WEIGHTS = pl.DataFrame(
    {"symbol": [], "weight": []},
    schema={"symbol": pl.Utf8, "weight": pl.Float64},
)


# ---------------------------------------------------------------------------
# Lot-size rounding helper
# ---------------------------------------------------------------------------


def _round_to_lot(qty: Decimal, lot_size: int) -> Decimal:
    """Round ``qty`` toward zero to the nearest ``lot_size`` multiple.

    Parameters
    ----------
    qty : Decimal
        The quantity to round (may be positive or negative).
    lot_size : int
        Minimum trading unit (e.g. 100 for A-shares).

    Returns
    -------
    Decimal
        Rounded quantity (always a multiple of ``lot_size``, toward zero).
    """
    if qty == _DECIMAL_ZERO:
        return qty
    lot = Decimal(str(lot_size))
    sign = Decimal("1") if qty > _DECIMAL_ZERO else Decimal("-1")
    return sign * (abs(qty) // lot) * lot


# ---------------------------------------------------------------------------
# Rebalance rule
# ---------------------------------------------------------------------------


class RebalanceRule(Protocol):
    """Protocol for rebalance timing rules."""

    def should_rebalance(
        self,
        ctx: BarContext,
        last_rebalance_dt: datetime | None,
    ) -> bool:
        """Return True if the portfolio should rebalance at this bar."""


class PeriodicRebalance:
    """Rebalance every N bars."""

    def __init__(self, every_n_bars: int = 1) -> None:
        if every_n_bars < 1:
            raise ValueError("every_n_bars must be >= 1")
        self.every_n_bars = every_n_bars

    def should_rebalance(
        self,
        ctx: BarContext,
        last_rebalance_dt: datetime | None,
    ) -> bool:
        if last_rebalance_dt is None:
            return True
        bars_after = ctx.history.bars.filter(pl.col("dt") > last_rebalance_dt)
        if bars_after.is_empty():
            return False
        n_unique = bars_after.select(pl.col("dt").n_unique()).item()
        return n_unique >= self.every_n_bars


# ---------------------------------------------------------------------------
# WeightAllocator — protocol for all weight allocators
# ---------------------------------------------------------------------------


@runtime_checkable
class WeightAllocator(Protocol):
    """Protocol for converting signal scores into portfolio weights.

    Implementations receive scores ``[symbol, score]`` and access to the
    current bar context for historical data, and must return
    ``[symbol, weight]``.
    """

    def allocate(self, scores: pl.DataFrame, ctx: BarContext) -> pl.DataFrame:
        """Convert ``[symbol, score]`` to ``[symbol, weight]``."""
        ...


# ---------------------------------------------------------------------------
# Constraints - weight clipping & scaling
# ---------------------------------------------------------------------------


@dataclass
class Constraints:
    """Portfolio weight constraints.

    Parameters
    ----------
    max_single_weight : Decimal
        Maximum absolute weight for any single symbol (default 1.0).
    gross_exposure : Decimal
        Maximum sum of absolute weights across all symbols (default 1.0).
    long_only : bool
        If True, negative weights are zeroed out (default False).
    """

    max_single_weight: Decimal = Decimal("1.0")
    gross_exposure: Decimal = Decimal("1.0")
    long_only: bool = False

    def __post_init__(self) -> None:
        _require_positive_decimal(self.max_single_weight, "max_single_weight")
        _require_positive_decimal(self.gross_exposure, "gross_exposure")

    def apply(self, weights: pl.DataFrame) -> pl.DataFrame:
        """Apply constraints to a ``[symbol, weight]`` DataFrame."""
        _require_columns(weights, ["symbol", "weight"])
        if weights.is_empty():
            return weights

        result = weights.clone()

        # Long-only: zero out negative weights
        if self.long_only:
            result = result.with_columns(
                pl.when(pl.col("weight") > 0.0)
                .then(pl.col("weight"))
                .otherwise(0.0)
                .alias("weight")
            )

        # Clip per-symbol
        max_single = float(self.max_single_weight)
        lower = 0.0 if self.long_only else -max_single
        result = result.with_columns(
            pl.col("weight").clip(lower_bound=lower, upper_bound=max_single).alias("weight")
        )

        # Scale gross exposure
        gross = float(self.gross_exposure)
        current_gross: float = result.select(pl.col("weight").abs().sum()).item()
        if current_gross > gross and current_gross > 0.0:
            scale = gross / current_gross
            result = result.with_columns((pl.col("weight") * scale).alias("weight"))

        return result


# ---------------------------------------------------------------------------
# Allocator — EqualWeight
# ---------------------------------------------------------------------------


@dataclass
class EqualWeight:
    """Assign equal weight to top-K and bottom-K symbols.

    Parameters
    ----------
    top_k : int
        Number of top-scoring symbols to hold long (default 10).
    bottom_k : int
        Number of bottom-scoring symbols to hold short (default 0).
        Ignored when ``long_only=True``.
    long_only : bool
        If True, only long positions are generated (default False).
    """

    top_k: int = 10
    bottom_k: int = 0
    long_only: bool = False

    def __post_init__(self) -> None:
        if self.top_k < 0:
            raise ValueError("top_k must be >= 0")
        if self.bottom_k < 0:
            raise ValueError("bottom_k must be >= 0")
        if self.top_k == 0 and self.bottom_k == 0:
            raise ValueError("at least one of top_k or bottom_k must be > 0")

    def allocate(self, scores: pl.DataFrame, ctx: BarContext) -> pl.DataFrame:
        """Convert ``[symbol, score]`` to ``[symbol, weight]``.

        Parameters
        ----------
        scores : pl.DataFrame
            DataFrame with ``symbol`` and ``score`` columns.
        ctx : BarContext
            Bar context (unused by EqualWeight, required by protocol).
        """
        _require_columns(scores, ["symbol", "score"])
        if scores.is_empty():
            return _EMPTY_WEIGHTS

        # Drop rows with null scores
        scores = scores.filter(pl.col("score").is_not_null())
        if scores.is_empty():
            return _EMPTY_WEIGHTS

        sorted_df = scores.sort("score", descending=True)
        n = sorted_df.height

        rows: list[dict[str, object]] = []
        used_symbols: set[str] = set()

        # Long positions
        if self.top_k > 0:
            k = min(self.top_k, n)
            long_wt = 1.0 / self.top_k
            for row in sorted_df.head(k).iter_rows(named=True):
                sym = str(row["symbol"])
                rows.append({"symbol": sym, "weight": long_wt})
                used_symbols.add(sym)

        # Short positions
        if self.bottom_k > 0 and not self.long_only:
            k = min(self.bottom_k + self.top_k, n)
            short_wt = -1.0 / self.bottom_k
            count = 0
            for row in sorted_df.tail(k).iter_rows(named=True):
                sym = str(row["symbol"])
                if sym not in used_symbols and count < self.bottom_k:
                    rows.append({"symbol": sym, "weight": short_wt})
                    count += 1

        if not rows:
            return _EMPTY_WEIGHTS

        return pl.DataFrame(rows, schema={"symbol": pl.Utf8, "weight": pl.Float64})


# ---------------------------------------------------------------------------
# Portfolio — orchestrator
# ---------------------------------------------------------------------------


@dataclass
class Portfolio:
    """Converts signal scores into OrderIntents via allocation + constraints.

    Parameters
    ----------
    allocator : WeightAllocator
        The allocation method for converting scores to weights.
    constraints : Constraints | None
        Optional weight constraints.
    rebalance : RebalanceRule | None
        Optional rebalance timing rule.
    lot_size : int
        Minimum trading unit (e.g. 100 for A-shares). Defaults to 100.
    """

    allocator: WeightAllocator
    constraints: Constraints | None = None
    rebalance: RebalanceRule | None = None
    preprocessor: SignalPreprocessor | None = None
    lot_size: int = 100

    # Internal: tracks last rebalance datetime
    _last_rebalance_dt: datetime | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.lot_size <= 0:
            raise StrategyError("lot_size must be positive")

    def build_orders(
        self,
        scores: pl.DataFrame,
        ctx: BarContext,
    ) -> list[OrderIntent]:
        """Convert signal scores to a list of OrderIntent objects.

        Steps: preprocess → rebalance check → allocate → constrain →
        compute NAV → target quantities → delta → OrderIntents.
        """
        if scores.is_empty():
            return []

        # 0. Preprocess scores
        if self.preprocessor is not None:
            scores = self.preprocessor.transform(scores, ctx)
            if scores.is_empty():
                return []

        # 1. Rebalance check
        if self.rebalance is not None and not self.rebalance.should_rebalance(
            ctx, self._last_rebalance_dt
        ):
            return []

        # 2. Allocate
        weights = self.allocator.allocate(scores, ctx)
        if weights.is_empty():
            return []

        # 3. Constrain
        if self.constraints is not None:
            weights = self.constraints.apply(weights)

        # 4. Extract prices from current bar
        prices: dict[str, Decimal] = {}
        for row in ctx.bar.select(["symbol", "close"]).iter_rows(named=True):
            close = row["close"]
            price = close if isinstance(close, Decimal) else Decimal(str(close))
            if price > _DECIMAL_ZERO:
                prices[str(row["symbol"])] = price

        # 5. Compute NAV
        nav = ctx.account.cash
        for sym, pos in (ctx.account.positions or {}).items():
            if sym in prices:
                nav += pos.qty * prices[sym]

        if nav <= _DECIMAL_ZERO:
            return []

        # 6. Convert weights → target quantities → intents
        intents: list[OrderIntent] = []
        for row in weights.iter_rows(named=True):
            symbol = str(row["symbol"])
            weight = Decimal(str(row["weight"]))
            price = prices.get(symbol)
            if price is None or price <= _DECIMAL_ZERO:
                continue

            # Target quantity (floor for long, floor(abs) with sign for short)
            target_notional = weight * nav
            target_qty = int(target_notional // price)

            current_qty = ctx.account.position(symbol).qty
            raw_delta = Decimal(str(target_qty)) - current_qty
            delta = _round_to_lot(raw_delta, self.lot_size)

            if delta > 0:
                intents.append(
                    OrderIntent(
                        symbol=symbol,
                        side=Side.BUY,
                        qty=delta,
                        order_type=OrderType.MARKET,
                    )
                )
            elif delta < 0:
                intents.append(
                    OrderIntent(
                        symbol=symbol,
                        side=Side.SELL,
                        qty=-delta,
                        order_type=OrderType.MARKET,
                    )
                )

        self._last_rebalance_dt = ctx.now
        return intents


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require_positive_decimal(value: Decimal, name: str) -> None:
    if not isinstance(value, Decimal):
        raise StrategyError(f"{name} must be decimal.Decimal")
    if value <= _DECIMAL_ZERO:
        raise StrategyError(f"{name} must be positive")


def _require_columns(df: pl.DataFrame, expected: list[str]) -> None:
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise StrategyError(f"DataFrame missing required columns: {', '.join(missing)}")
