"""Fee and slippage cost models for backtest execution."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from getrich_backtest.types import Side


_DECIMAL_ZERO = Decimal("0")


def _require_non_negative(value: Decimal, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be decimal.Decimal")
    if value < _DECIMAL_ZERO:
        raise ValueError(f"{name} must be non-negative")
    return value


# ── Fee Models ──────────────────────────────────────────────────────────


class FeeModel(Protocol):
    """Protocol for computing fill fees."""

    def compute(
        self,
        qty: Decimal,
        price: Decimal,
        side: Side,
        asset_class: str | None = None,
    ) -> Decimal:
        """Return the fee for a fill with the given parameters."""
        ...


@dataclass(frozen=True)
class ZeroFee:
    """Zero fee (default)."""

    def compute(
        self,
        qty: Decimal,
        price: Decimal,
        side: Side,
        asset_class: str | None = None,
    ) -> Decimal:
        return _DECIMAL_ZERO


@dataclass(frozen=True)
class FixedFee:
    """Fixed fee per fill regardless of size."""

    amount: Decimal

    def __post_init__(self) -> None:
        _require_non_negative(self.amount, "amount")

    def compute(
        self,
        qty: Decimal,
        price: Decimal,
        side: Side,
        asset_class: str | None = None,
    ) -> Decimal:
        return self.amount


@dataclass(frozen=True)
class PerShareFee:
    """Fee proportional to the number of shares/contracts."""

    rate: Decimal

    def __post_init__(self) -> None:
        _require_non_negative(self.rate, "rate")

    def compute(
        self,
        qty: Decimal,
        price: Decimal,
        side: Side,
        asset_class: str | None = None,
    ) -> Decimal:
        return self.rate * abs(qty)


@dataclass(frozen=True)
class PercentageFee:
    """Fee as a fraction of the trade notional (e.g. 0.0003 for 3 bps)."""

    rate: Decimal

    def __post_init__(self) -> None:
        _require_non_negative(self.rate, "rate")

    def compute(
        self,
        qty: Decimal,
        price: Decimal,
        side: Side,
        asset_class: str | None = None,
    ) -> Decimal:
        return self.rate * abs(qty) * price


@dataclass(frozen=True)
class CompositeFee:
    """Aggregate of multiple fee models (fees are summed)."""

    models: tuple[FeeModel, ...]

    def compute(
        self,
        qty: Decimal,
        price: Decimal,
        side: Side,
        asset_class: str | None = None,
    ) -> Decimal:
        total = _DECIMAL_ZERO
        for model in self.models:
            total += model.compute(qty, price, side, asset_class)
        return total


# ── Slippage Models ─────────────────────────────────────────────────────


class SlippageModel(Protocol):
    """Protocol for computing fill price slippage."""

    def compute(
        self,
        price: Decimal,
        qty: Decimal,
        side: Side,
    ) -> Decimal:
        """Return the slippage amount to apply to the fill price.

        For BUY orders the slippage is added to the base price.
        For SELL orders the slippage is subtracted.
        """
        ...


@dataclass(frozen=True)
class ZeroSlippage:
    """Zero slippage (default)."""

    def compute(
        self,
        price: Decimal,
        qty: Decimal,
        side: Side,
    ) -> Decimal:
        return _DECIMAL_ZERO


@dataclass(frozen=True)
class FixedSlippage:
    """Fixed slippage amount per fill (price offset)."""

    amount: Decimal

    def __post_init__(self) -> None:
        _require_non_negative(self.amount, "amount")

    def compute(
        self,
        price: Decimal,
        qty: Decimal,
        side: Side,
    ) -> Decimal:
        return self.amount


@dataclass(frozen=True)
class BpsSlippage:
    """Slippage as a fraction of the fill price in basis points.

    One basis point = 1/10000 of the price.
    """

    bps: Decimal

    def __post_init__(self) -> None:
        _require_non_negative(self.bps, "bps")

    def compute(
        self,
        price: Decimal,
        qty: Decimal,
        side: Side,
    ) -> Decimal:
        return price * self.bps / Decimal("10000")
