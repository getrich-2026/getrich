from decimal import Decimal

import pytest

from getrich_backtest import OrderIntent, OrderIntentError, OrderType, Side, TakeProfitStopLoss


def test_order_intent_accepts_valid_qty_market_order() -> None:
    intent = OrderIntent(symbol="000001.SZ", side=Side.BUY, qty=Decimal("100"))
    assert intent.qty == Decimal("100")
    assert intent.order_type is OrderType.MARKET


def test_order_intent_accepts_valid_weight_order() -> None:
    intent = OrderIntent(symbol="000001.SZ", side=Side.BUY, weight=Decimal("0.10"))
    assert intent.weight == Decimal("0.10")


def test_order_intent_rejects_both_qty_and_weight() -> None:
    with pytest.raises(OrderIntentError, match="exactly one"):
        OrderIntent(symbol="000001.SZ", side=Side.BUY, qty=Decimal("100"), weight=Decimal("0.1"))


def test_order_intent_rejects_neither_qty_nor_weight() -> None:
    with pytest.raises(OrderIntentError, match="exactly one"):
        OrderIntent(symbol="000001.SZ", side=Side.BUY)


def test_order_intent_rejects_float_qty() -> None:
    with pytest.raises(OrderIntentError, match="decimal.Decimal"):
        OrderIntent(symbol="000001.SZ", side=Side.BUY, qty=100.0)  # type: ignore[arg-type]


def test_order_intent_rejects_non_positive_qty() -> None:
    with pytest.raises(OrderIntentError, match="positive"):
        OrderIntent(symbol="000001.SZ", side=Side.BUY, qty=Decimal("0"))


def test_order_intent_rejects_limit_order_without_limit_price() -> None:
    with pytest.raises(OrderIntentError, match="limit_price"):
        OrderIntent(
            symbol="000001.SZ",
            side=Side.BUY,
            qty=Decimal("100"),
            order_type=OrderType.LIMIT,
        )


def test_order_intent_rejects_stop_order_without_stop_price() -> None:
    with pytest.raises(OrderIntentError, match="stop_price"):
        OrderIntent(
            symbol="000001.SZ",
            side=Side.BUY,
            qty=Decimal("100"),
            order_type=OrderType.STOP,
        )


def test_order_intent_rejects_float_limit_price() -> None:
    with pytest.raises(OrderIntentError, match="decimal.Decimal"):
        OrderIntent(
            symbol="000001.SZ",
            side=Side.BUY,
            qty=Decimal("100"),
            order_type=OrderType.LIMIT,
            limit_price=10.0,  # type: ignore[arg-type]
        )


def test_take_profit_stop_loss_validates_decimal_fields() -> None:
    tpsl = TakeProfitStopLoss(trigger=Decimal("10.5"), trailing=Decimal("0.1"))
    assert tpsl.trigger == Decimal("10.5")


def test_take_profit_stop_loss_rejects_float_trigger() -> None:
    with pytest.raises(OrderIntentError, match="decimal.Decimal"):
        TakeProfitStopLoss(trigger=10.5)  # type: ignore[arg-type]
