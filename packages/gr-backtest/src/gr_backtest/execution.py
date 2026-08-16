"""Minimal order execution models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from math import isnan
from typing import Any

import polars as pl

from gr_backtest.account import Account
from gr_backtest.cost import FeeModel, SlippageModel, ZeroFee, ZeroSlippage
from gr_backtest.exceptions import ExecutionError
from gr_backtest.strategy.order import OrderIntent
from gr_backtest.time import require_shanghai_aware
from gr_backtest.types import OrderType, Side


_DECIMAL_ZERO = Decimal("0")
_BUY_SIDES = {Side.BUY, Side.OPEN_LONG, Side.CLOSE_SHORT}
_SELL_SIDES = {Side.SELL, Side.CLOSE_LONG, Side.OPEN_SHORT}
_SUPPORTED_MARKET_SIDES = _BUY_SIDES | _SELL_SIDES
# Weight resolution: sides that ADD exposure resolve against cash;
# sides that REMOVE exposure resolve against existing position magnitude.
_CASH_RESOLVE_SIDES = {Side.BUY, Side.OPEN_LONG, Side.OPEN_SHORT}
_POSITION_RESOLVE_SIDES = {Side.SELL, Side.CLOSE_LONG, Side.CLOSE_SHORT}


class OrderStatus(str, Enum):
    """Execution order status."""

    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


def _require_decimal(value: object, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise ExecutionError(f"{field_name} must be decimal.Decimal")
    return value


def _require_positive_decimal(value: object, field_name: str) -> Decimal:
    decimal_value = _require_decimal(value, field_name)
    if decimal_value <= _DECIMAL_ZERO:
        raise ExecutionError(f"{field_name} must be positive")
    return decimal_value


def _price_to_decimal(value: Any) -> Decimal:
    if value is None:
        raise ExecutionError("bar price must not be null")
    if isinstance(value, Decimal):
        price = value
    else:
        if isinstance(value, float) and isnan(value):
            raise ExecutionError("bar price must not be NaN")
        price = Decimal(str(value))
    if price <= _DECIMAL_ZERO:
        raise ExecutionError("bar price must be positive")
    return price


@dataclass
class Order:
    """Executable order created from a strategy order intent."""

    order_id: str
    intent: OrderIntent
    strategy_name: str
    created_dt: datetime
    created_index: int
    eligible_index: int
    status: OrderStatus = OrderStatus.PENDING
    filled_qty: Decimal = _DECIMAL_ZERO
    reject_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.order_id.strip():
            raise ExecutionError("order_id must be non-empty")
        if not self.strategy_name.strip():
            raise ExecutionError("strategy_name must be non-empty")
        require_shanghai_aware(self.created_dt)
        if self.created_index < 0:
            raise ExecutionError("created_index must be non-negative")
        if self.eligible_index <= self.created_index:
            raise ExecutionError("eligible_index must be later than created_index")
        _require_decimal(self.filled_qty, "filled_qty")
        if self.filled_qty < _DECIMAL_ZERO:
            raise ExecutionError("filled_qty must be non-negative")

    @property
    def symbol(self) -> str:
        """Return the order symbol."""
        return self.intent.symbol

    @property
    def side(self) -> Side:
        """Return the order side."""
        return self.intent.side

    @property
    def qty(self) -> Decimal:
        """Return the order quantity, if P0 execution supports this intent."""
        if self.intent.qty is None:
            raise ExecutionError("weight orders do not have an executable qty in P0")
        return self.intent.qty

    @property
    def remaining_qty(self) -> Decimal:
        """Return the unfilled quantity."""
        return (self.intent.qty - self.filled_qty) if self.intent.qty is not None else Decimal("0")

    def resolve_qty(self, account: Account, fill_price: Decimal) -> Decimal:
        """Resolve the executable quantity from intent qty or weight."""
        if self.intent.qty is not None:
            return self.intent.qty
        if self.intent.weight is not None:
            return self._resolve_weight(account, fill_price)
        raise ExecutionError("order has neither qty nor weight")

    def _resolve_weight(self, account: Account, fill_price: Decimal) -> Decimal:
        if self.side in _CASH_RESOLVE_SIDES:
            raw = self.intent.weight * account.cash / fill_price  # type: ignore[operator]
        else:
            position = account.positions.get(self.symbol)
            pos_qty = position.qty if position is not None else _DECIMAL_ZERO
            raw = self.intent.weight * abs(pos_qty)  # type: ignore[operator]
        return Decimal(str(int(raw)))  # floor (truncate toward zero)

    def reject(self, reason: str) -> None:
        """Mark the order as rejected with a reason."""
        self.status = OrderStatus.REJECTED
        self.reject_reason = reason

    def expire(self) -> None:
        """Mark the order as expired."""
        if self.status in {OrderStatus.PENDING, OrderStatus.ACCEPTED}:
            self.status = OrderStatus.EXPIRED


@dataclass(frozen=True)
class Fill:
    """A fully executed fill."""

    fill_id: str
    order_id: str
    strategy_name: str
    symbol: str
    side: Side
    qty: Decimal
    price: Decimal
    notional: Decimal
    fee: Decimal
    fill_time: datetime
    bar_dt: datetime
    slippage: Decimal = _DECIMAL_ZERO
    tag: str | None = None

    def __post_init__(self) -> None:
        if not self.fill_id.strip():
            raise ExecutionError("fill_id must be non-empty")
        if not self.order_id.strip():
            raise ExecutionError("order_id must be non-empty")
        if not self.strategy_name.strip():
            raise ExecutionError("strategy_name must be non-empty")
        if not self.symbol.strip():
            raise ExecutionError("fill symbol must be non-empty")
        _require_positive_decimal(self.qty, "fill qty")
        _require_positive_decimal(self.price, "fill price")
        _require_decimal(self.notional, "fill notional")
        _require_decimal(self.fee, "fill fee")
        _require_decimal(self.slippage, "fill slippage")
        if self.notional != self.qty * self.price:
            raise ExecutionError("fill notional must equal qty * price")
        if self.fee < _DECIMAL_ZERO:
            raise ExecutionError("fill fee must be non-negative")
        if self.slippage < _DECIMAL_ZERO:
            raise ExecutionError("fill slippage must be non-negative")
        require_shanghai_aware(self.fill_time)
        require_shanghai_aware(self.bar_dt)


class NextBarMatchingModel:
    """Market-order matcher that fills on a future bar open.

    Supports MARKET, LIMIT, STOP, and STOP_LIMIT order types using OHLC
    bar data to determine intra-bar fill conditions.
    """

    def __init__(
        self,
        execution_lag_bars: int = 1,
        fee_model: FeeModel | None = None,
        slippage_model: SlippageModel | None = None,
    ) -> None:
        if execution_lag_bars < 1:
            raise ExecutionError("execution_lag_bars must be at least 1")
        self.execution_lag_bars = execution_lag_bars
        self.fee_model = fee_model if fee_model is not None else ZeroFee()
        self.slippage_model = slippage_model if slippage_model is not None else ZeroSlippage()

    def match(
        self,
        order: Order,
        bar: pl.DataFrame,
        account: Account,
        *,
        fill_id: str,
    ) -> Fill | None:
        """Try to match one eligible order against the current bar."""
        if order.status not in {OrderStatus.PENDING, OrderStatus.ACCEPTED}:
            return None

        order.status = OrderStatus.ACCEPTED
        rejection = self._rejection_reason(order, account)
        if rejection is not None:
            order.reject(rejection)
            return None

        symbol_bar = bar.filter(pl.col("symbol") == order.symbol)
        if symbol_bar.is_empty():
            order.reject("symbol is not available on eligible bar")
            return None

        row = symbol_bar.row(0, named=True)

        # Tradability checks
        is_suspended = row.get("is_suspended")
        if is_suspended is True or is_suspended == 1:
            order.reject("symbol is suspended")
            return None

        base_price = self._get_fill_base_price(row, order)
        if base_price is None:
            order.reject("fill condition was not met on eligible bar")
            return None

        qty = order.resolve_qty(account, base_price)
        if qty <= _DECIMAL_ZERO:
            order.reject("resolved qty must be positive")
            return None

        # Apply slippage
        slippage = self.slippage_model.compute(base_price, qty, order.side)
        is_buy = order.side in _BUY_SIDES
        fill_price = base_price + slippage if is_buy else base_price - slippage
        if fill_price <= _DECIMAL_ZERO:
            order.reject("slippage produced non-positive fill price")
            return None

        # Price limit checks
        limit_up = row.get("limit_up")
        limit_down = row.get("limit_down")
        if limit_up is not None and is_buy and fill_price > _price_to_decimal(limit_up):
            order.reject("price exceeds limit_up")
            return None
        if limit_down is not None and not is_buy and fill_price < _price_to_decimal(limit_down):
            order.reject("price below limit_down")
            return None

        notional = qty * fill_price
        fee = self.fee_model.compute(qty, fill_price, order.side)

        if order.side in _BUY_SIDES and account.cash < notional + fee:
            order.reject("insufficient cash")
            return None
        if order.side in {Side.SELL, Side.CLOSE_LONG}:
            pos_qty = account.view().position(order.symbol).qty
            if pos_qty < qty:
                order.reject("insufficient position quantity")
                return None
        if order.side == Side.CLOSE_SHORT:
            pos_qty = account.view().position(order.symbol).qty
            if pos_qty >= _DECIMAL_ZERO or abs(pos_qty) < qty:
                order.reject("insufficient short position quantity")
                return None

        bar_dt = row["dt"]
        if not isinstance(bar_dt, datetime):
            raise ExecutionError("bar dt must be a datetime")
        require_shanghai_aware(bar_dt)

        fill = Fill(
            fill_id=fill_id,
            order_id=order.order_id,
            strategy_name=order.strategy_name,
            symbol=order.symbol,
            side=order.side,
            qty=qty,
            price=fill_price,
            notional=notional,
            fee=fee,
            fill_time=bar_dt,
            bar_dt=bar_dt,
            slippage=slippage,
            tag=order.intent.tag,
        )
        order.filled_qty = qty
        order.status = OrderStatus.FILLED
        return fill

    def _get_fill_base_price(
        self,
        row: dict[str, object],
        order: Order,
    ) -> Decimal | None:
        """Determine the base fill price for an order on a bar.

        Returns ``None`` when the fill condition is not met.

        Fill prices are deterministic, using OHLC bar data without
        intra-bar timing assumptions, avoiding look-ahead bias.
        """
        order_type = order.intent.order_type
        is_buy = order.side in _BUY_SIDES

        open_price = _price_to_decimal(row["open"])
        high = _price_to_decimal(row["high"])
        low = _price_to_decimal(row["low"])

        if order_type == OrderType.MARKET:
            return open_price

        if order_type == OrderType.LIMIT:
            limit_price = order.intent.limit_price
            if limit_price is None:
                return None
            if is_buy:
                return min(limit_price, open_price) if low <= limit_price else None
            else:
                return max(limit_price, open_price) if high >= limit_price else None

        if order_type == OrderType.STOP:
            stop_price = order.intent.stop_price
            if stop_price is None:
                return None
            if is_buy:
                return max(stop_price, open_price) if high >= stop_price else None
            else:
                return min(stop_price, open_price) if low <= stop_price else None

        if order_type == OrderType.STOP_LIMIT:
            stop_price = order.intent.stop_price
            limit_price = order.intent.limit_price
            if stop_price is None or limit_price is None:
                return None

            if is_buy:
                if high < stop_price:
                    return None
                return min(limit_price, open_price) if low <= limit_price else None
            else:
                if low > stop_price:
                    return None
                return max(limit_price, open_price) if high >= limit_price else None

        return None

    def _rejection_reason(self, order: Order, account: Account) -> str | None:
        if order.side not in _SUPPORTED_MARKET_SIDES:
            return f"{order.side.value} is not supported in P0 execution"
        if order.intent.qty is None and order.intent.weight is None:
            return "order must have qty or weight"
        if order.intent.qty is not None and order.intent.qty <= _DECIMAL_ZERO:
            return "order qty must be positive"
        if order.intent.order_type == OrderType.LIMIT and order.intent.limit_price is None:
            return "LIMIT order requires limit_price"
        stop_types = {OrderType.STOP, OrderType.STOP_LIMIT}
        if order.intent.order_type in stop_types and order.intent.stop_price is None:
            return f"{order.intent.order_type.value} order requires stop_price"
        if order.intent.order_type == OrderType.STOP_LIMIT and order.intent.limit_price is None:
            return "STOP_LIMIT order requires limit_price"
        return None
