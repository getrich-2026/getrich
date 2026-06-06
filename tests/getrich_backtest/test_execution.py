from datetime import datetime
from decimal import Decimal

import polars as pl
import pytest

from getrich_backtest import (
    Account,
    ExecutionError,
    Fill,
    NextBarMatchingModel,
    Order,
    OrderIntent,
    OrderStatus,
    OrderType,
    Side,
    get_shanghai_tz,
)


def bars() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "dt": [datetime(2026, 1, 2, 9, 30, tzinfo=get_shanghai_tz())],
            "symbol": ["000001.SZ"],
            "open": [Decimal("10")],
            "high": [Decimal("99")],
            "low": [Decimal("1")],
            "close": [Decimal("20")],
            "volume": [1000.0],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


def order(intent: OrderIntent | None = None) -> Order:
    return Order(
        order_id="order-1",
        intent=intent or OrderIntent(symbol="000001.SZ", side=Side.BUY, qty=Decimal("10")),
        strategy_name="TestStrategy",
        created_dt=datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz()),
        created_index=0,
        eligible_index=1,
    )


def test_next_bar_matching_model_defaults_to_one_bar_lag() -> None:
    model = NextBarMatchingModel()
    assert model.execution_lag_bars == 1
    with pytest.raises(ExecutionError, match="at least 1"):
        NextBarMatchingModel(execution_lag_bars=0)


def test_market_buy_fills_at_eligible_bar_open() -> None:
    model = NextBarMatchingModel()
    account = Account(initial_cash=Decimal("1000"))
    fill = model.match(order(), bars(), account, fill_id="fill-1")

    assert isinstance(fill, Fill)
    assert fill.price == Decimal("10")
    assert fill.notional == Decimal("100")
    assert fill.bar_dt == datetime(2026, 1, 2, 9, 30, tzinfo=get_shanghai_tz())
    assert fill.price != Decimal("99")


def test_successful_match_marks_order_filled_with_decimal_fields() -> None:
    model = NextBarMatchingModel()
    account = Account(initial_cash=Decimal("1000"))
    executable_order = order()
    fill = model.match(executable_order, bars(), account, fill_id="fill-1")

    assert fill is not None
    assert executable_order.status == OrderStatus.FILLED
    assert executable_order.filled_qty == Decimal("10")
    assert isinstance(fill.qty, Decimal)
    assert isinstance(fill.price, Decimal)
    assert fill.notional == fill.qty * fill.price


def test_limit_buy_fills_when_low_touches_limit_price() -> None:
    model = NextBarMatchingModel()
    account = Account(initial_cash=Decimal("1000"))
    executable_order = order(
        OrderIntent(
            symbol="000001.SZ",
            side=Side.BUY,
            qty=Decimal("10"),
            order_type=OrderType.LIMIT,
            limit_price=Decimal("10"),
        )
    )
    fill = model.match(executable_order, bars(), account, fill_id="fill-1")

    assert fill is not None
    assert fill.price == Decimal("10")  # min(10, 10) = 10
    assert executable_order.status == OrderStatus.FILLED


def test_limit_buy_does_not_fill_when_low_above_limit() -> None:
    model = NextBarMatchingModel()
    account = Account(initial_cash=Decimal("1000"))
    executable_order = order(
        OrderIntent(
            symbol="000001.SZ",
            side=Side.BUY,
            qty=Decimal("10"),
            order_type=OrderType.LIMIT,
            limit_price=Decimal("0.5"),
        )
    )
    fill = model.match(executable_order, bars(), account, fill_id="fill-1")

    assert fill is None
    assert executable_order.status == OrderStatus.REJECTED


def test_limit_sell_fills_when_high_touches_limit_price() -> None:
    model = NextBarMatchingModel()
    account = Account(initial_cash=Decimal("1000"))
    account.apply(
        Fill(
            fill_id="f0",
            order_id="o0",
            strategy_name="TestStrategy",
            symbol="000001.SZ",
            side=Side.BUY,
            qty=Decimal("10"),
            price=Decimal("10"),
            notional=Decimal("100"),
            fee=Decimal("0"),
            fill_time=datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz()),
            bar_dt=datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz()),
        )
    )
    executable_order = order(
        OrderIntent(
            symbol="000001.SZ",
            side=Side.SELL,
            qty=Decimal("10"),
            order_type=OrderType.LIMIT,
            limit_price=Decimal("15"),
        )
    )
    fill = model.match(executable_order, bars(), account, fill_id="fill-1")

    assert fill is not None
    assert fill.price == Decimal("15")  # max(15, 10) = 15


def test_stop_buy_triggers_when_high_reaches_stop() -> None:
    model = NextBarMatchingModel()
    account = Account(initial_cash=Decimal("1000"))
    executable_order = order(
        OrderIntent(
            symbol="000001.SZ",
            side=Side.BUY,
            qty=Decimal("10"),
            order_type=OrderType.STOP,
            stop_price=Decimal("15"),
        )
    )
    fill = model.match(executable_order, bars(), account, fill_id="fill-1")

    assert fill is not None
    assert fill.price == Decimal("15")  # max(15, 10) = 15


def test_stop_buy_does_not_trigger_when_high_below_stop() -> None:
    model = NextBarMatchingModel()
    account = Account(initial_cash=Decimal("1000"))
    executable_order = order(
        OrderIntent(
            symbol="000001.SZ",
            side=Side.BUY,
            qty=Decimal("10"),
            order_type=OrderType.STOP,
            stop_price=Decimal("100"),
        )
    )
    fill = model.match(executable_order, bars(), account, fill_id="fill-1")

    assert fill is None
    assert executable_order.status == OrderStatus.REJECTED


def test_stop_sell_triggers_when_low_reaches_stop() -> None:
    model = NextBarMatchingModel()
    account = Account(initial_cash=Decimal("1000"))
    account.apply(
        Fill(
            fill_id="f0",
            order_id="o0",
            strategy_name="TestStrategy",
            symbol="000001.SZ",
            side=Side.BUY,
            qty=Decimal("10"),
            price=Decimal("10"),
            notional=Decimal("100"),
            fee=Decimal("0"),
            fill_time=datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz()),
            bar_dt=datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz()),
        )
    )
    executable_order = order(
        OrderIntent(
            symbol="000001.SZ",
            side=Side.SELL,
            qty=Decimal("10"),
            order_type=OrderType.STOP,
            stop_price=Decimal("5"),
        )
    )
    fill = model.match(executable_order, bars(), account, fill_id="fill-1")

    assert fill is not None
    assert fill.price == Decimal("5")  # min(5, 10) = 5


def test_stop_limit_buy_fills_when_both_conditions_met() -> None:
    model = NextBarMatchingModel()
    account = Account(initial_cash=Decimal("1000"))
    executable_order = order(
        OrderIntent(
            symbol="000001.SZ",
            side=Side.BUY,
            qty=Decimal("10"),
            order_type=OrderType.STOP_LIMIT,
            stop_price=Decimal("15"),
            limit_price=Decimal("12"),
        )
    )
    fill = model.match(executable_order, bars(), account, fill_id="fill-1")

    assert fill is not None
    # stop triggered (99 >= 15), limit low condition met (1 <= 12)
    assert fill.price == Decimal("10")  # min(12, 10) = 10


def test_stop_limit_buy_does_not_fill_when_limit_not_met() -> None:
    model = NextBarMatchingModel()
    account = Account(initial_cash=Decimal("1000"))
    executable_order = order(
        OrderIntent(
            symbol="000001.SZ",
            side=Side.BUY,
            qty=Decimal("10"),
            order_type=OrderType.STOP_LIMIT,
            stop_price=Decimal("15"),
            limit_price=Decimal("0.5"),
        )
    )
    fill = model.match(executable_order, bars(), account, fill_id="fill-1")

    assert fill is None
    assert executable_order.status == OrderStatus.REJECTED


def test_weight_buy_resolves_qty_from_cash() -> None:
    """weight=0.5 with cash=1000, price=10 → qty = floor(0.5*1000/10) = 50"""
    model = NextBarMatchingModel()
    account = Account(initial_cash=Decimal("1000"))
    executable_order = order(OrderIntent(symbol="000001.SZ", side=Side.BUY, weight=Decimal("0.5")))
    fill = model.match(executable_order, bars(), account, fill_id="fill-1")

    assert fill is not None
    assert executable_order.status == OrderStatus.FILLED
    assert fill.qty == Decimal("50")
    assert fill.notional == Decimal("500")


def test_weight_sell_resolves_qty_from_position() -> None:
    """weight=0.5 with position qty=100 → qty = floor(0.5*100) = 50"""
    model = NextBarMatchingModel()
    account = Account(initial_cash=Decimal("1000"))
    account.apply(
        Fill(
            fill_id="f0",
            order_id="o0",
            strategy_name="TestStrategy",
            symbol="000001.SZ",
            side=Side.BUY,
            qty=Decimal("100"),
            price=Decimal("10"),
            notional=Decimal("1000"),
            fee=Decimal("0"),
            fill_time=datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz()),
            bar_dt=datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz()),
        )
    )
    executable_order = order(OrderIntent(symbol="000001.SZ", side=Side.SELL, weight=Decimal("0.5")))
    fill = model.match(executable_order, bars(), account, fill_id="fill-1")

    assert fill is not None
    assert executable_order.status == OrderStatus.FILLED
    assert fill.qty == Decimal("50")


def test_weight_buy_resolves_qty_zero_for_tiny_cash() -> None:
    """weight=0.1 with cash=1, price=10 → qty = floor(0.1/10) = 0 → rejected"""
    model = NextBarMatchingModel()
    account = Account(initial_cash=Decimal("1"))
    executable_order = order(OrderIntent(symbol="000001.SZ", side=Side.BUY, weight=Decimal("0.1")))
    fill = model.match(executable_order, bars(), account, fill_id="fill-1")

    assert fill is None
    assert executable_order.status == OrderStatus.REJECTED


def test_short_side_is_rejected() -> None:
    model = NextBarMatchingModel()
    account = Account(initial_cash=Decimal("1000"))
    executable_order = order(
        OrderIntent(symbol="000001.SZ", side=Side.OPEN_SHORT, qty=Decimal("10"))
    )
    fill = model.match(executable_order, bars(), account, fill_id="fill-1")

    assert fill is not None
    assert executable_order.status == OrderStatus.FILLED


def test_close_short_is_accepted() -> None:
    """CLOSE_SHORT is now a supported market side."""
    model = NextBarMatchingModel()
    account = Account(initial_cash=Decimal("1000"))
    # Create a short position first
    dt = datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz())
    short_fill = Fill(
        fill_id="short-1",
        order_id="order-0",
        strategy_name="TestStrategy",
        symbol="000001.SZ",
        side=Side.OPEN_SHORT,
        qty=Decimal("10"),
        price=Decimal("10"),
        notional=Decimal("100"),
        fee=Decimal("0"),
        fill_time=dt,
        bar_dt=dt,
    )
    account.apply(short_fill)

    executable_order = order(
        OrderIntent(symbol="000001.SZ", side=Side.CLOSE_SHORT, qty=Decimal("5"))
    )
    fill = model.match(executable_order, bars(), account, fill_id="fill-1")
    assert fill is not None
    assert executable_order.status == OrderStatus.FILLED


def test_close_short_rejects_insufficient_cash() -> None:
    """CLOSE_SHORT rejects when cash is insufficient."""
    model = NextBarMatchingModel()
    account = Account(initial_cash=Decimal("10"))
    dt = datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz())
    # Short 1 share at 10 -> cash = 20, position qty = -1
    short_fill = Fill(
        fill_id="short-1",
        order_id="order-0",
        strategy_name="TestStrategy",
        symbol="000001.SZ",
        side=Side.OPEN_SHORT,
        qty=Decimal("1"),
        price=Decimal("10"),
        notional=Decimal("10"),
        fee=Decimal("0"),
        fill_time=dt,
        bar_dt=dt,
    )
    account.apply(short_fill)

    # Try to cover qty=5 at 10 -> cost=50 > cash=20
    executable_order = order(
        OrderIntent(symbol="000001.SZ", side=Side.CLOSE_SHORT, qty=Decimal("5"))
    )
    fill = model.match(executable_order, bars(), account, fill_id="fill-1")
    assert fill is None
    assert executable_order.status == OrderStatus.REJECTED


def test_close_short_rejects_no_short_position() -> None:
    """CLOSE_SHORT rejects when there is no short position."""
    model = NextBarMatchingModel()
    account = Account(initial_cash=Decimal("1000"))
    executable_order = order(
        OrderIntent(symbol="000001.SZ", side=Side.CLOSE_SHORT, qty=Decimal("5"))
    )
    fill = model.match(executable_order, bars(), account, fill_id="fill-1")
    assert fill is None
    assert "insufficient short position" in (executable_order.reject_reason or "")


def test_open_short_weight_resolves_against_cash() -> None:
    """OPEN_SHORT weight uses cash-based resolution: weight * cash / price."""
    model = NextBarMatchingModel()
    account = Account(initial_cash=Decimal("1000"))
    executable_order = order(
        OrderIntent(symbol="000001.SZ", side=Side.OPEN_SHORT, weight=Decimal("0.5"))
    )
    fill = model.match(executable_order, bars(), account, fill_id="fill-1")
    assert fill is not None
    assert fill.qty == Decimal("50")  # 0.5 * 1000 / 10


def test_close_short_weight_resolves_against_position() -> None:
    """CLOSE_SHORT weight resolves against abs(position qty)."""
    model = NextBarMatchingModel()
    account = Account(initial_cash=Decimal("1000"))
    dt = datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz())
    short_fill = Fill(
        fill_id="short-1",
        order_id="order-0",
        strategy_name="TestStrategy",
        symbol="000001.SZ",
        side=Side.OPEN_SHORT,
        qty=Decimal("100"),
        price=Decimal("10"),
        notional=Decimal("1000"),
        fee=Decimal("0"),
        fill_time=dt,
        bar_dt=dt,
    )
    account.apply(short_fill)
    # Now account has qty=-100, cash=2000

    executable_order = order(
        OrderIntent(symbol="000001.SZ", side=Side.CLOSE_SHORT, weight=Decimal("0.5"))
    )
    fill = model.match(executable_order, bars(), account, fill_id="fill-1")
    assert fill is not None
    assert fill.qty == Decimal("50")  # 0.5 * 100


def test_insufficient_cash_order_is_rejected() -> None:
    model = NextBarMatchingModel()
    account = Account(initial_cash=Decimal("10"))
    executable_order = order(OrderIntent(symbol="000001.SZ", side=Side.BUY, qty=Decimal("10")))
    fill = model.match(executable_order, bars(), account, fill_id="fill-1")

    assert fill is None
    assert executable_order.status == OrderStatus.REJECTED
    assert executable_order.reject_reason == "insufficient cash"


def test_order_expires_when_unfilled() -> None:
    executable_order = order()
    executable_order.expire()
    assert executable_order.status == OrderStatus.EXPIRED


# ── Tradability ─────────────────────────────────────────────────────


def suspended_bars() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "dt": [datetime(2026, 1, 2, 9, 30, tzinfo=get_shanghai_tz())],
            "symbol": ["000001.SZ"],
            "open": [Decimal("10")],
            "high": [Decimal("11")],
            "low": [Decimal("9")],
            "close": [Decimal("10.5")],
            "volume": [1000.0],
            "is_suspended": [True],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


def limit_up_bars() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "dt": [datetime(2026, 1, 2, 9, 30, tzinfo=get_shanghai_tz())],
            "symbol": ["000001.SZ"],
            "open": [Decimal("10")],
            "high": [Decimal("11")],
            "low": [Decimal("9")],
            "close": [Decimal("10.5")],
            "volume": [1000.0],
            "limit_up": [Decimal("10.5")],
            "limit_down": [Decimal("9.5")],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


def test_order_rejected_when_symbol_suspended() -> None:
    model = NextBarMatchingModel()
    account = Account(initial_cash=Decimal("1000"))
    executable_order = order()
    fill = model.match(executable_order, suspended_bars(), account, fill_id="fill-1")
    assert fill is None
    assert executable_order.status == OrderStatus.REJECTED
    assert executable_order.reject_reason == "symbol is suspended"


def test_buy_within_limit_up_succeeds() -> None:
    """open=10, fill_price=10, limit_up=10.5 → fills normally."""
    model = NextBarMatchingModel()
    account = Account(initial_cash=Decimal("1000"))
    fill = model.match(order(), limit_up_bars(), account, fill_id="fill-1")
    assert fill is not None


def test_missing_columns_backward_compatible() -> None:
    """Bars without is_suspended/limit_up columns should trade normally."""
    model = NextBarMatchingModel()
    account = Account(initial_cash=Decimal("1000"))
    fill = model.match(order(), bars(), account, fill_id="fill-1")
    assert fill is not None
