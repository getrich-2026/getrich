"""Risk control tests for margin accounts."""

from datetime import datetime
from decimal import Decimal

import pytest

from getrich_backtest import (
    Account,
    Fill,
    MarginError,
    RiskConfig,
    RiskManager,
    Side,
    get_shanghai_tz,
)
from getrich_backtest.account import Position


DT = datetime(2026, 1, 2, 9, 30, tzinfo=get_shanghai_tz())


def fill(
    *,
    symbol: str = "IF",
    side: Side = Side.OPEN_LONG,
    qty: Decimal = Decimal("1"),
    price: Decimal = Decimal("100"),
) -> Fill:
    return Fill(
        fill_id=f"fill-{side.value}-{symbol}",
        order_id="order-1",
        strategy_name="TestStrategy",
        symbol=symbol,
        side=side,
        qty=qty,
        price=price,
        notional=qty * price,
        fee=Decimal("0"),
        fill_time=DT,
        bar_dt=DT,
    )


def test_risk_config_defaults() -> None:
    config = RiskConfig()
    assert config.margin_call_threshold == Decimal("1.0")
    assert config.liquidation_threshold == Decimal("0.8")
    assert config.liquidation_slippage_bps == Decimal("30")


def test_risk_config_rejects_non_decimal() -> None:
    with pytest.raises(MarginError, match="decimal.Decimal"):
        RiskConfig(margin_call_threshold=1.0)  # type: ignore[arg-type]


def test_risk_config_rejects_negative_threshold() -> None:
    with pytest.raises(MarginError, match="non-negative"):
        RiskConfig(liquidation_threshold=Decimal("-0.1"))


def test_check_margin_call_breached() -> None:
    account = Account(initial_cash=Decimal("1000"), cash=Decimal("100"))
    account.margin_state.maintenance_margin = Decimal("200")
    assert RiskManager().check_margin_call(account) is True


def test_check_margin_call_safe() -> None:
    account = Account(initial_cash=Decimal("1000"), cash=Decimal("300"))
    account.margin_state.maintenance_margin = Decimal("200")
    assert RiskManager().check_margin_call(account) is False


def test_check_margin_call_zero_margin() -> None:
    account = Account(initial_cash=Decimal("1000"), cash=Decimal("0"))
    assert RiskManager().check_margin_call(account) is False


def test_check_liquidation_breached() -> None:
    account = Account(initial_cash=Decimal("1000"), cash=Decimal("100"))
    account.margin_state.maintenance_margin = Decimal("200")
    manager = RiskManager(RiskConfig(liquidation_threshold=Decimal("0.8")))
    assert manager.check_liquidation(account) is True


def test_check_liquidation_safe() -> None:
    account = Account(initial_cash=Decimal("1000"), cash=Decimal("180"))
    account.margin_state.maintenance_margin = Decimal("200")
    manager = RiskManager(RiskConfig(liquidation_threshold=Decimal("0.8")))
    assert manager.check_liquidation(account) is False


def test_check_leverage_breached() -> None:
    pos = Position(symbol="IF", qty=Decimal("10"), last_price=Decimal("100"))
    account = Account(initial_cash=Decimal("100"), cash=Decimal("0"), positions={"IF": pos})
    manager = RiskManager(RiskConfig(max_leverage=Decimal("0.5")))
    assert manager.check_leverage(account, {"IF": Decimal("100")}) is True


def test_check_leverage_safe() -> None:
    pos = Position(symbol="IF", qty=Decimal("1"), last_price=Decimal("100"))
    account = Account(initial_cash=Decimal("1000"), cash=Decimal("1000"), positions={"IF": pos})
    manager = RiskManager(RiskConfig(max_leverage=Decimal("5")))
    assert manager.check_leverage(account, {"IF": Decimal("100")}) is False


def test_check_concentration_breached() -> None:
    pos = Position(symbol="IF", qty=Decimal("10"), last_price=Decimal("100"))
    account = Account(initial_cash=Decimal("1000"), cash=Decimal("1000"), positions={"IF": pos})
    manager = RiskManager(RiskConfig(max_position_concentration=Decimal("0.4")))
    assert manager.check_concentration(account, {"IF": Decimal("100")}) == ["IF"]


def test_check_concentration_safe() -> None:
    pos = Position(symbol="IF", qty=Decimal("1"), last_price=Decimal("100"))
    account = Account(initial_cash=Decimal("1000"), cash=Decimal("1000"), positions={"IF": pos})
    manager = RiskManager(RiskConfig(max_position_concentration=Decimal("0.4")))
    assert manager.check_concentration(account, {"IF": Decimal("100")}) == []


def test_liquidate_all_closes_long_position() -> None:
    account = Account(initial_cash=Decimal("1000"), cash=Decimal("1000"))
    account.apply(fill(side=Side.BUY, qty=Decimal("5"), price=Decimal("100")))
    account.margin_state.maintenance_margin = Decimal("1000")
    events = RiskManager().liquidate_all(account, {"IF": Decimal("100")}, DT)
    assert len(events) == 1
    assert events[0].symbol == "IF"
    assert events[0].qty_liquidated == Decimal("5")
    assert account.positions["IF"].qty == Decimal("0")


def test_liquidate_all_closes_short_position() -> None:
    account = Account(initial_cash=Decimal("1000"), cash=Decimal("1000"))
    account.apply(fill(side=Side.OPEN_SHORT, qty=Decimal("5"), price=Decimal("100")))
    account.margin_state.maintenance_margin = Decimal("1000")
    events = RiskManager().liquidate_all(account, {"IF": Decimal("100")}, DT)
    assert len(events) == 1
    assert events[0].symbol == "IF"
    assert events[0].qty_liquidated == Decimal("5")
    assert account.positions["IF"].qty == Decimal("0")


def test_liquidate_all_largest_notional_first() -> None:
    small = Position(
        symbol="SMALL",
        qty=Decimal("1"),
        avg_cost=Decimal("10"),
        last_price=Decimal("10"),
    )
    large = Position(
        symbol="LARGE",
        qty=Decimal("10"),
        avg_cost=Decimal("10"),
        last_price=Decimal("10"),
    )
    account = Account(
        initial_cash=Decimal("1000"),
        cash=Decimal("1000"),
        positions={"SMALL": small, "LARGE": large},
    )
    account.margin_state.maintenance_margin = Decimal("1000")
    events = RiskManager().liquidate_all(
        account,
        {"SMALL": Decimal("10"), "LARGE": Decimal("10")},
        DT,
    )
    assert events[0].symbol == "LARGE"
