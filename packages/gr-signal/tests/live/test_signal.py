"""Tests for the Signal data model."""

from datetime import datetime
from decimal import Decimal

import pytest
from gr_backtest import get_shanghai_tz
from gr_signal.live import Signal


TZ = get_shanghai_tz()


class TestSignal:
    def test_defaults(self) -> None:
        """Minimal construction uses defaults for optional fields."""
        s = Signal(symbol="A", action="buy")
        assert s.symbol == "A"
        assert s.action == "buy"
        assert s.signal_type == "entry"
        assert s.direction is None
        assert s.urgency == "normal"
        assert s.status == "active"
        assert s.confidence is None
        assert s.trigger_price is None
        assert s.trigger_time is None

    def test_frozen(self) -> None:
        """Signal is immutable."""
        s = Signal(symbol="A", action="buy")
        with pytest.raises(AttributeError):
            s.symbol = "B"  # type: ignore[misc]

    def test_all_fields(self) -> None:
        """All fields can be set at construction."""
        now = datetime(2026, 6, 1, 9, 30, tzinfo=TZ)
        s = Signal(
            symbol="IF2409",
            action="buy",
            signal_type="entry",
            direction="long",
            symbol_name="沪深300股指期货2409",
            exchange="CFFEX",
            trigger_price=Decimal("3500.50"),
            target_price=Decimal("3600.00"),
            stop_loss_price=Decimal("3400.00"),
            suggested_quantity=2,
            position_pct=Decimal("0.15"),
            confidence=Decimal("0.85"),
            urgency="high",
            reason="均线金叉",
            trigger_time=now,
            status="active",
        )
        assert s.symbol == "IF2409"
        assert s.action == "buy"
        assert s.trigger_price == Decimal("3500.50")
        assert s.confidence == Decimal("0.85")
        assert s.trigger_time == now
        assert s.reason == "均线金叉"

    def test_equality(self) -> None:
        """Two Signals with same fields are equal (frozen dataclass)."""
        s1 = Signal(symbol="A", action="buy", confidence=Decimal("0.5"))
        s2 = Signal(symbol="A", action="buy", confidence=Decimal("0.5"))
        assert s1 == s2

    def test_inequality(self) -> None:
        """Different fields produce unequal Signals."""
        s1 = Signal(symbol="A", action="buy")
        s2 = Signal(symbol="B", action="buy")
        assert s1 != s2
