"""Multi-strategy capital allocation.

Provides the ``FixedAllocator`` for dividing capital among strategies
by fixed percentage weights.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from getrich_backtest.exceptions import BacktestError
from getrich_backtest.strategy.base import Strategy


_DECIMAL_ZERO = Decimal("0")


@dataclass(frozen=True)
class Allocation:
    """Capital allocation for one strategy in a multi-strategy run."""

    strategy_name: str
    capital_weight: Decimal


class FixedAllocator:
    """Allocate capital by fixed percentage weights.

    Parameters
    ----------
    weights : dict[str, Decimal] | None
        Mapping of strategy names to capital weights.
        If ``None``, equal weight is assigned to all strategies.
        Weights are automatically normalised to sum to 1.0.

    Examples
    --------
    >>> alloc = FixedAllocator({"strat_a": Decimal("0.6"), "strat_b": Decimal("0.4")})
    >>> alloc.allocate([strat_a, strat_b])
    [Allocation("strat_a", Decimal("0.6")), Allocation("strat_b", Decimal("0.4"))]
    """

    def __init__(self, weights: dict[str, Decimal] | None = None) -> None:
        self._weights: dict[str, Decimal] | None = None
        if weights is not None:
            for name, w in weights.items():
                if w <= _DECIMAL_ZERO:
                    raise BacktestError(f"capital_weight for '{name}' must be positive")
                if not name.strip():
                    raise BacktestError("strategy name must be non-empty")
            self._weights = dict(weights)

    def allocate(
        self,
        strategies: Sequence[Strategy],
    ) -> list[Allocation]:
        """Return capital allocations for the given strategies."""
        if not strategies:
            return []

        names = [s.name for s in strategies]

        if self._weights is not None:
            raw_weights = {n: self._weights.get(n, _DECIMAL_ZERO) for n in names}
        else:
            raw_weights = {n: Decimal("1.0") for n in names}

        total = sum(raw_weights.values(), _DECIMAL_ZERO)
        if total <= _DECIMAL_ZERO:
            return [Allocation(n, _DECIMAL_ZERO) for n in names]

        return [Allocation(n, w / total) for n, w in raw_weights.items()]
