"""Tests for Account.apply_corporate_action()."""

from datetime import datetime
from decimal import Decimal

import pytest

from getrich_backtest import CorporateActionError, Fill, Side, get_shanghai_tz
from getrich_backtest.account import Account


TZ = get_shanghai_tz()


def _buy_fill(
    symbol: str = "A", qty: Decimal = Decimal("100"), price: Decimal = Decimal("10")
) -> Fill:
    dt = datetime(2026, 1, 2, 9, 30, tzinfo=TZ)
    return Fill(
        fill_id="f1",
        order_id="o1",
        strategy_name="Test",
        symbol=symbol,
        side=Side.BUY,
        qty=qty,
        price=price,
        notional=qty * price,
        fee=Decimal("0"),
        fill_time=dt,
        bar_dt=dt,
    )


class TestAccountCorporateActions:
    def test_dividend_increases_cash(self) -> None:
        """Cash dividend adds to cash balance."""
        a = Account(initial_cash=Decimal("100000"), cash=Decimal("50000"))
        a.apply(_buy_fill(qty=Decimal("1000"), price=Decimal("10")))
        assert a.cash == Decimal("40000")

        # Dividend: 0.5 per share, 1000 shares, 10% tax
        a.apply_corporate_action(
            symbol="A",
            action_type="dividend",
            amount=0.5,
        )
        # net = 1000 * 0.5 * (1 - 0.10) = 450
        assert a.cash == Decimal("40450")

    def test_dividend_no_position_skipped(self) -> None:
        """Dividend for a symbol without position does nothing."""
        a = Account(initial_cash=Decimal("100000"))
        initial_cash = a.cash
        a.apply_corporate_action(
            symbol="A",
            action_type="dividend",
            amount=0.5,
        )
        assert a.cash == initial_cash

    def test_split_multiplies_quantity(self) -> None:
        """Stock split adjusts position qty and avg_cost."""
        a = Account(initial_cash=Decimal("100000"), cash=Decimal("50000"))
        a.apply(_buy_fill(qty=Decimal("100"), price=Decimal("10")))
        pos = a.positions["A"]
        assert pos.qty == Decimal("100")
        assert pos.avg_cost == Decimal("10")

        # 2:1 split
        a.apply_corporate_action(symbol="A", action_type="split", split_ratio=2.0)
        assert pos.qty == Decimal("200")
        assert pos.avg_cost == Decimal("5")  # 10 / 2

    def test_split_reverse(self) -> None:
        """Reverse split (1:2) reduces quantity."""
        a = Account(initial_cash=Decimal("100000"), cash=Decimal("50000"))
        a.apply(_buy_fill(qty=Decimal("200"), price=Decimal("10")))
        pos = a.positions["A"]

        # 1:2 reverse split
        a.apply_corporate_action(symbol="A", action_type="split", split_ratio=0.5)
        assert pos.qty == Decimal("100")
        assert pos.avg_cost == Decimal("20")  # 10 / 0.5

    def test_bonus_increases_quantity(self) -> None:
        """Bonus shares increase position qty."""
        a = Account(initial_cash=Decimal("100000"), cash=Decimal("50000"))
        a.apply(_buy_fill(qty=Decimal("100"), price=Decimal("10")))
        pos = a.positions["A"]

        # 10% bonus: 1 bonus share per 10 held
        a.apply_corporate_action(symbol="A", action_type="bonus", bonus_ratio=0.1)
        assert pos.qty == Decimal("110")  # 100 * 1.1
        assert pos.avg_cost == Decimal("9.090909090909090909090909091")  # 10 / 1.1

    def test_rights_skipped(self) -> None:
        """Rights issue is skipped (default waive)."""
        a = Account(initial_cash=Decimal("100000"))
        a.apply_corporate_action(symbol="A", action_type="rights")
        # No change
        assert a.cash == Decimal("100000")

    def test_dividend_missing_amount_raises(self) -> None:
        """Dividend without amount raises CorporateActionError."""
        a = Account(initial_cash=Decimal("100000"))
        with pytest.raises(CorporateActionError, match="dividend requires"):
            a.apply_corporate_action(symbol="A", action_type="dividend")

    def test_split_missing_ratio_raises(self) -> None:
        """Split without split_ratio raises CorporateActionError."""
        a = Account(initial_cash=Decimal("100000"))
        with pytest.raises(CorporateActionError, match="split requires"):
            a.apply_corporate_action(symbol="A", action_type="split")

    def test_bonus_missing_ratio_raises(self) -> None:
        """Bonus without bonus_ratio raises CorporateActionError."""
        a = Account(initial_cash=Decimal("100000"))
        with pytest.raises(CorporateActionError, match="bonus requires"):
            a.apply_corporate_action(symbol="A", action_type="bonus")

    def test_unknown_action_type_raises(self) -> None:
        """Unknown action_type raises CorporateActionError."""
        a = Account(initial_cash=Decimal("100000"))
        with pytest.raises(CorporateActionError, match="unknown action_type"):
            a.apply_corporate_action(symbol="A", action_type="unknown_type")

    def test_dividend_custom_tax_rate(self) -> None:
        """Custom dividend tax rate applies correctly."""
        a = Account(initial_cash=Decimal("100000"), cash=Decimal("50000"))
        a.apply(_buy_fill(qty=Decimal("1000"), price=Decimal("10")))
        a.apply_corporate_action(
            symbol="A",
            action_type="dividend",
            amount=1.0,
            dividend_tax_rate=Decimal("0.20"),
        )
        # net = 1000 * 1.0 * (1 - 0.20) = 800
        assert a.cash == Decimal("40800")
