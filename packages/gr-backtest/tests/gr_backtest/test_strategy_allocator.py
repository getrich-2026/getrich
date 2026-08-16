"""Tests for the FixedAllocator."""

from decimal import Decimal

import pytest
from gr_backtest import BacktestError
from gr_backtest.strategy import FixedAllocator
from gr_backtest.strategy.base import Strategy


class _DummyStrat(Strategy):
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name


class TestFixedAllocator:
    def test_equal_weight_three_strategies(self) -> None:
        alloc = FixedAllocator()
        result = alloc.allocate([_DummyStrat("A"), _DummyStrat("B"), _DummyStrat("C")])
        assert len(result) == 3
        for allocation in result:
            assert allocation.capital_weight == pytest.approx(Decimal("1") / 3)

    def test_explicit_weights_normalize(self) -> None:
        alloc = FixedAllocator({"A": Decimal("2"), "B": Decimal("1")})
        result = alloc.allocate([_DummyStrat("A"), _DummyStrat("B")])
        assert result[0].capital_weight == pytest.approx(Decimal("2") / 3)
        assert result[1].capital_weight == pytest.approx(Decimal("1") / 3)

    def test_single_strategy_gets_one(self) -> None:
        alloc = FixedAllocator()
        result = alloc.allocate([_DummyStrat("X")])
        assert len(result) == 1
        assert result[0].capital_weight == Decimal("1.0")

    def test_empty_strategies(self) -> None:
        alloc = FixedAllocator()
        result = alloc.allocate([])
        assert result == []

    def test_explicit_single_strategy(self) -> None:
        alloc = FixedAllocator({"A": Decimal("1.0")})
        result = alloc.allocate([_DummyStrat("A")])
        assert result[0].capital_weight == Decimal("1.0")

    def test_rejects_zero_weight(self) -> None:
        with pytest.raises(BacktestError, match="positive"):
            FixedAllocator({"A": Decimal("0")})

    def test_rejects_negative_weight(self) -> None:
        with pytest.raises(BacktestError, match="positive"):
            FixedAllocator({"A": Decimal("-0.5")})

    def test_rejects_empty_name(self) -> None:
        with pytest.raises(BacktestError, match="non-empty"):
            FixedAllocator({"": Decimal("0.5")})

    def test_unlisted_strategy_gets_zero(self) -> None:
        alloc = FixedAllocator({"A": Decimal("0.6")})
        result = alloc.allocate([_DummyStrat("A"), _DummyStrat("B")])
        # B was not in weights → gets 0, so A gets 1.0 after normalization
        assert result[0].capital_weight == pytest.approx(Decimal("1.0"))
        assert result[1].capital_weight == pytest.approx(Decimal("0"))

    def test_allocation_immutable(self) -> None:
        alloc = FixedAllocator({"A": Decimal("0.5")})
        result = alloc.allocate([_DummyStrat("A")])
        assert result[0].strategy_name == "A"
        assert result[0].capital_weight == Decimal("1.0")
