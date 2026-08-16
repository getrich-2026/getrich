"""Strategy-facing order intent types."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from gr_backtest.exceptions import OrderIntentError
from gr_backtest.types import OrderType, Side, TimeInForce


_DECIMAL_ZERO = Decimal("0")


def _require_decimal(value: Any, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise OrderIntentError(f"{field_name} must be decimal.Decimal")
    return value


def _require_positive_decimal(value: Any, field_name: str) -> Decimal:
    decimal_value = _require_decimal(value, field_name)
    if decimal_value <= _DECIMAL_ZERO:
        raise OrderIntentError(f"{field_name} must be positive")
    return decimal_value


@dataclass(frozen=True)
class TakeProfitStopLoss:
    """Take-profit or stop-loss trigger definition."""

    trigger: Decimal
    order_type: OrderType = OrderType.MARKET
    limit_price: Decimal | None = None
    trailing: Decimal | None = None

    def __post_init__(self) -> None:
        _require_positive_decimal(self.trigger, "trigger")
        if self.limit_price is not None:
            _require_positive_decimal(self.limit_price, "limit_price")
        if self.trailing is not None:
            _require_positive_decimal(self.trailing, "trailing")
        if self.order_type in {OrderType.LIMIT, OrderType.STOP_LIMIT} and self.limit_price is None:
            raise OrderIntentError("limit_price is required for limit TPSL orders")


@dataclass(frozen=True)
class OrderIntent:
    """A strategy request to create an order later in the execution layer."""

    symbol: str
    side: Side
    qty: Decimal | None = None
    weight: Decimal | None = None
    order_type: OrderType = OrderType.MARKET
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.DAY
    take_profit: TakeProfitStopLoss | None = None
    stop_loss: TakeProfitStopLoss | None = None
    tag: str | None = None
    parent_order_id: str | None = None

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise OrderIntentError("symbol must be non-empty")
        if (self.qty is None) == (self.weight is None):
            raise OrderIntentError("exactly one of qty or weight must be provided")
        if self.qty is not None:
            _require_positive_decimal(self.qty, "qty")
        if self.weight is not None:
            _require_decimal(self.weight, "weight")
        if self.limit_price is not None:
            _require_positive_decimal(self.limit_price, "limit_price")
        if self.stop_price is not None:
            _require_positive_decimal(self.stop_price, "stop_price")
        if self.order_type in {OrderType.LIMIT, OrderType.STOP_LIMIT} and self.limit_price is None:
            raise OrderIntentError("limit_price is required for LIMIT and STOP_LIMIT orders")
        if self.order_type in {OrderType.STOP, OrderType.STOP_LIMIT} and self.stop_price is None:
            raise OrderIntentError("stop_price is required for STOP and STOP_LIMIT orders")
