"""Risk controls for margin accounts and forced liquidation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from gr_backtest.exceptions import MarginError
from gr_backtest.time import require_shanghai_aware


if TYPE_CHECKING:
    from gr_backtest.account import Account


_DECIMAL_ZERO = Decimal("0")
_BPS_DENOMINATOR = Decimal("10000")


def _require_decimal(value: object, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise MarginError(f"{field_name} must be decimal.Decimal")
    return value


def _require_non_negative_decimal(value: object, field_name: str) -> Decimal:
    decimal_value = _require_decimal(value, field_name)
    if decimal_value < _DECIMAL_ZERO:
        raise MarginError(f"{field_name} must be non-negative")
    return decimal_value


@dataclass(frozen=True)
class RiskConfig:
    """Configuration for account-level risk checks."""

    margin_call_threshold: Decimal = Decimal("1.0")
    liquidation_threshold: Decimal = Decimal("0.8")
    liquidation_slippage_bps: Decimal = Decimal("30")
    max_leverage: Decimal | None = None
    max_position_concentration: Decimal | None = None

    def __post_init__(self) -> None:
        _require_non_negative_decimal(self.margin_call_threshold, "margin_call_threshold")
        _require_non_negative_decimal(self.liquidation_threshold, "liquidation_threshold")
        _require_non_negative_decimal(self.liquidation_slippage_bps, "liquidation_slippage_bps")
        if self.max_leverage is not None:
            _require_non_negative_decimal(self.max_leverage, "max_leverage")
        if self.max_position_concentration is not None:
            _require_non_negative_decimal(
                self.max_position_concentration,
                "max_position_concentration",
            )

    def to_dict(self) -> dict[str, str | None]:
        """Return a stable dict representation for run configuration."""
        return {
            "margin_call_threshold": str(self.margin_call_threshold),
            "liquidation_threshold": str(self.liquidation_threshold),
            "liquidation_slippage_bps": str(self.liquidation_slippage_bps),
            "max_leverage": str(self.max_leverage) if self.max_leverage is not None else None,
            "max_position_concentration": (
                str(self.max_position_concentration)
                if self.max_position_concentration is not None
                else None
            ),
        }


@dataclass(frozen=True)
class LiquidationEvent:
    """A synthetic forced-liquidation event."""

    dt: datetime
    symbol: str
    qty_liquidated: Decimal
    estimated_price: Decimal
    realized_pnl: Decimal
    reason: str

    def __post_init__(self) -> None:
        require_shanghai_aware(self.dt)
        if not self.symbol.strip():
            raise MarginError("liquidation symbol must be non-empty")
        _require_non_negative_decimal(self.qty_liquidated, "qty_liquidated")
        _require_non_negative_decimal(self.estimated_price, "estimated_price")
        _require_decimal(self.realized_pnl, "realized_pnl")
        if not self.reason.strip():
            raise MarginError("liquidation reason must be non-empty")


class RiskManager:
    """Evaluate and enforce risk constraints for a margin account."""

    def __init__(self, config: RiskConfig | None = None) -> None:
        self.config = config if config is not None else RiskConfig()

    def check_margin_call(self, account: Account) -> bool:
        """Return True when available cash is below the margin-call threshold."""
        maintenance = account.margin_state.maintenance_margin
        if maintenance <= _DECIMAL_ZERO:
            return False
        threshold = maintenance * self.config.margin_call_threshold
        return account.available_cash < threshold

    def check_liquidation(self, account: Account) -> bool:
        """Return True when available cash is below the liquidation threshold."""
        maintenance = account.margin_state.maintenance_margin
        if maintenance <= _DECIMAL_ZERO:
            return False
        threshold = maintenance * self.config.liquidation_threshold
        return account.available_cash < threshold

    def check_leverage(
        self,
        account: Account,
        last_prices: Mapping[str, Decimal],
    ) -> bool:
        """Return True when gross exposure / equity exceeds max_leverage."""
        if self.config.max_leverage is None:
            return False
        equity = account.equity(last_prices)
        if equity <= _DECIMAL_ZERO:
            return True
        leverage = account.gross_exposure(last_prices) / equity
        return leverage > self.config.max_leverage

    def check_concentration(
        self,
        account: Account,
        last_prices: Mapping[str, Decimal],
    ) -> list[str]:
        """Return symbols whose notional exposure exceeds the concentration cap."""
        if self.config.max_position_concentration is None:
            return []
        equity = account.equity(last_prices)
        if equity <= _DECIMAL_ZERO:
            return [symbol for symbol, pos in account.positions.items() if pos.qty != _DECIMAL_ZERO]

        breached: list[str] = []
        for symbol, position in account.positions.items():
            if position.qty == _DECIMAL_ZERO:
                continue
            price = last_prices.get(symbol, position.last_price)
            if price is None:
                continue
            exposure = abs(position.qty) * price * position.multiplier
            if exposure / equity > self.config.max_position_concentration:
                breached.append(symbol)
        return breached

    def liquidate_all(
        self,
        account: Account,
        last_prices: Mapping[str, Decimal],
        dt: datetime,
    ) -> list[LiquidationEvent]:
        """Force-close positions from largest notional to smallest."""
        require_shanghai_aware(dt)
        events: list[LiquidationEvent] = []
        candidates: list[tuple[Decimal, str, Decimal]] = []
        for symbol, position in account.positions.items():
            if position.qty == _DECIMAL_ZERO:
                continue
            price = last_prices.get(symbol, position.last_price)
            if price is None:
                continue
            notional = abs(position.qty) * price * position.multiplier
            candidates.append((notional, symbol, price))

        candidates.sort(key=lambda item: item[0], reverse=True)
        slippage = self.config.liquidation_slippage_bps / _BPS_DENOMINATOR
        for _notional, symbol, mark_price in candidates:
            position = account.positions.get(symbol)
            if position is None or position.qty == _DECIMAL_ZERO:
                continue
            close_price = mark_price * (Decimal("1") - slippage)
            if position.qty < _DECIMAL_ZERO:
                close_price = mark_price * (Decimal("1") + slippage)
            if close_price <= _DECIMAL_ZERO:
                close_price = mark_price

            qty = abs(position.qty)
            realized_before = account.total_realized_pnl
            account.force_close_position(symbol=symbol, price=close_price, dt=dt)
            account.margin_state.forced_liquidation_triggered = True
            events.append(
                LiquidationEvent(
                    dt=dt,
                    symbol=symbol,
                    qty_liquidated=qty,
                    estimated_price=close_price,
                    realized_pnl=account.total_realized_pnl - realized_before,
                    reason="margin_liquidation",
                )
            )
            if not self.check_liquidation(account):
                break
        return events
