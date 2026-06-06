"""Tests for the MarginCalculator."""

from decimal import Decimal

import polars as pl

from getrich_backtest import MarginCalculator
from getrich_backtest.types import Side


def test_empty_init_returns_zero() -> None:
    calc = MarginCalculator()
    margin = calc.initial_margin("IF", Decimal("2"), Decimal("5000"), Side.OPEN_LONG)
    assert margin == Decimal("0")


def test_from_instruments() -> None:
    instruments = pl.DataFrame(
        {
            "symbol": ["IF"],
            "margin_ratio_long": [0.15],
            "margin_ratio_short": [0.15],
            "multiplier": [300.0],
        }
    )
    calc = MarginCalculator(instruments)
    margin = calc.initial_margin("IF", Decimal("2"), Decimal("5000"), Side.OPEN_LONG)
    assert margin == Decimal("450000")  # 2 * 5000 * 300 * 0.15


def test_equity_returns_zero() -> None:
    """Equity symbols without margin_ratio return 0 margin."""
    instruments = pl.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "asset_class": ["equity_a"],
        }
    )
    calc = MarginCalculator(instruments)
    margin = calc.initial_margin("000001.SZ", Decimal("100"), Decimal("10"), Side.BUY)
    assert margin == Decimal("0")


def test_uses_long_ratio_for_buy() -> None:
    """OPEN_LONG uses margin_ratio_long."""
    instruments = pl.DataFrame(
        {
            "symbol": ["IF"],
            "margin_ratio_long": [0.15],
            "margin_ratio_short": [0.10],
            "multiplier": [300.0],
        }
    )
    calc = MarginCalculator(instruments)
    margin_long = calc.initial_margin("IF", Decimal("2"), Decimal("5000"), Side.OPEN_LONG)
    assert margin_long == Decimal("450000")


def test_maintenance_margin_equals_initial() -> None:
    """Phase 1: maintenance margin = initial margin."""
    instruments = pl.DataFrame(
        {
            "symbol": ["IF"],
            "margin_ratio_long": [0.15],
            "multiplier": [300.0],
        }
    )
    calc = MarginCalculator(instruments)
    init = calc.initial_margin("IF", Decimal("2"), Decimal("5000"), Side.OPEN_LONG)
    maint = calc.maintenance_margin("IF", Decimal("2"), Decimal("5000"))
    assert maint == init


def test_total_initial_margin() -> None:
    instruments = pl.DataFrame(
        {
            "symbol": ["IF", "IC"],
            "margin_ratio_long": [0.15, 0.13],
            "margin_ratio_short": [0.15, 0.13],
            "multiplier": [300.0, 200.0],
        }
    )
    calc = MarginCalculator(instruments)
    total = calc.total_initial_margin(
        symbols=["IF", "IC"],
        qtys=[Decimal("2"), Decimal("3")],
        prices=[Decimal("5000"), Decimal("6000")],
        sides=[Side.OPEN_LONG, Side.OPEN_LONG],
    )
    # IF: 2 * 5000 * 300 * 0.15 = 450000
    # IC: 3 * 6000 * 200 * 0.13 = 468000
    assert total == Decimal("918000")


def test_update_instruments_refreshes_cache() -> None:
    instruments1 = pl.DataFrame(
        {
            "symbol": ["IF"],
            "margin_ratio_long": [0.15],
            "multiplier": [300.0],
        }
    )
    calc = MarginCalculator(instruments1)
    assert calc.initial_margin("IF", Decimal("1"), Decimal("5000"), Side.OPEN_LONG) == Decimal(
        "225000"
    )

    instruments2 = pl.DataFrame(
        {
            "symbol": ["IF"],
            "margin_ratio_long": [0.20],  # changed ratio
            "multiplier": [300.0],
        }
    )
    calc.update_instruments(instruments2)
    assert calc.initial_margin("IF", Decimal("1"), Decimal("5000"), Side.OPEN_LONG) == Decimal(
        "300000"
    )


def test_handles_null_ratios() -> None:
    """Null margin_ratio columns are skipped, defaulting to 0."""
    instruments = pl.DataFrame(
        {
            "symbol": ["IF"],
            "margin_ratio_long": [None],
            "multiplier": [300.0],
        }
    )
    calc = MarginCalculator(instruments)
    margin = calc.initial_margin("IF", Decimal("2"), Decimal("5000"), Side.OPEN_LONG)
    assert margin == Decimal("0")


def test_uses_short_ratio_for_open_short() -> None:
    """OPEN_SHORT uses margin_ratio_short (different from long ratio)."""
    instruments = pl.DataFrame(
        {
            "symbol": ["IF"],
            "margin_ratio_long": [0.15],
            "margin_ratio_short": [0.10],
            "multiplier": [300.0],
        }
    )
    calc = MarginCalculator(instruments)
    margin = calc.initial_margin("IF", Decimal("2"), Decimal("5000"), Side.OPEN_SHORT)
    assert margin == Decimal("300000")  # 2 * 5000 * 300 * 0.10
