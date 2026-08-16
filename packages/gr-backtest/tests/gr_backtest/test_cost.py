from datetime import datetime
from decimal import Decimal

import polars as pl
import pytest
from gr_backtest import (
    Backtest,
    BpsSlippage,
    CompositeFee,
    DataFrameBarLoader,
    FixedFee,
    FixedSlippage,
    OrderIntent,
    PercentageFee,
    PerShareFee,
    Side,
    Strategy,
    ZeroFee,
    ZeroSlippage,
    get_shanghai_tz,
)


# ── Fee Models ────────────────────────────────────────────────────────


def test_zero_fee_returns_zero() -> None:
    model = ZeroFee()
    assert model.compute(Decimal("10"), Decimal("100"), Side.BUY) == Decimal("0")


def test_fixed_fee_returns_constant() -> None:
    model = FixedFee(Decimal("5"))
    assert model.compute(Decimal("10"), Decimal("100"), Side.BUY) == Decimal("5")


def test_fixed_fee_rejects_negative() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        FixedFee(Decimal("-1"))


def test_per_share_fee_proportional_to_qty() -> None:
    model = PerShareFee(Decimal("0.01"))
    assert model.compute(Decimal("100"), Decimal("10"), Side.BUY) == Decimal("1")
    assert model.compute(Decimal("200"), Decimal("10"), Side.BUY) == Decimal("2")


def test_percentage_fee_proportional_to_notional() -> None:
    model = PercentageFee(Decimal("0.001"))
    assert model.compute(Decimal("100"), Decimal("10"), Side.BUY) == Decimal("1")


def test_composite_fee_sums_all_models() -> None:
    model = CompositeFee(models=(FixedFee(Decimal("1")), PerShareFee(Decimal("0.01"))))
    assert model.compute(Decimal("100"), Decimal("10"), Side.BUY) == Decimal("2")


# ── Slippage Models ───────────────────────────────────────────────────


def test_zero_slippage_returns_zero() -> None:
    model = ZeroSlippage()
    assert model.compute(Decimal("10"), Decimal("100"), Side.BUY) == Decimal("0")


def test_fixed_slippage_returns_constant() -> None:
    model = FixedSlippage(Decimal("0.05"))
    assert model.compute(Decimal("10"), Decimal("100"), Side.BUY) == Decimal("0.05")


def test_bps_slippage_proportional_to_price() -> None:
    model = BpsSlippage(Decimal("10"))  # 10 bps
    assert model.compute(Decimal("100"), Decimal("100"), Side.BUY) == Decimal("0.1")
    assert model.compute(Decimal("50"), Decimal("100"), Side.BUY) == Decimal("0.05")


def test_bps_slippage_rejects_negative() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        BpsSlippage(Decimal("-1"))


# ── Integration with Execution ────────────────────────────────────────


def bars() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "dt": [
                datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz()),
                datetime(2026, 1, 2, 9, 30, tzinfo=get_shanghai_tz()),
            ],
            "symbol": ["000001.SZ", "000001.SZ"],
            "open": [Decimal("10"), Decimal("11")],
            "high": [Decimal("11"), Decimal("12")],
            "low": [Decimal("9"), Decimal("10")],
            "close": [Decimal("10.5"), Decimal("11.5")],
            "volume": [1000.0, 1100.0],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


class BuyOnFirstBar(Strategy):
    def __init__(self) -> None:
        self.calls = 0

    def on_bar(self, ctx: object) -> list[OrderIntent] | None:
        self.calls += 1
        if self.calls == 1:
            return [OrderIntent(symbol="000001.SZ", side=Side.BUY, qty=Decimal("10"))]
        return None


def test_backtest_with_fixed_fee() -> None:
    bt = Backtest(
        strategy=BuyOnFirstBar(),
        bar_loader=DataFrameBarLoader(bars()),
        symbols=["000001.SZ"],
        start=datetime(2026, 1, 1, tzinfo=get_shanghai_tz()),
        end=datetime(2026, 1, 3, tzinfo=get_shanghai_tz()),
        initial_cash=Decimal("1000"),
        fee_model=FixedFee(Decimal("2")),
    )
    result = bt.run()
    assert len(result.fills) == 1
    assert result.fills[0].fee == Decimal("2")
    # cash: 1000 - 10*11 - 2 = 1000 - 110 - 2 = 888
    assert result.final_account.cash == Decimal("888")


def test_backtest_with_bps_slippage() -> None:
    bt = Backtest(
        strategy=BuyOnFirstBar(),
        bar_loader=DataFrameBarLoader(bars()),
        symbols=["000001.SZ"],
        start=datetime(2026, 1, 1, tzinfo=get_shanghai_tz()),
        end=datetime(2026, 1, 3, tzinfo=get_shanghai_tz()),
        initial_cash=Decimal("1000"),
        slippage_model=BpsSlippage(Decimal("50")),  # 50 bps = 0.5%
    )
    result = bt.run()
    assert len(result.fills) == 1
    # base_price = 11, slippage = 11 * 50/10000 = 0.055
    # BUY: fill_price = 11 + 0.055 = 11.055
    assert result.fills[0].price == Decimal("11.055")
    assert result.fills[0].slippage == Decimal("0.055")
    # notional = 10 * 11.055 = 110.55
    assert result.fills[0].notional == Decimal("110.55")


def test_backtest_with_composite_fee() -> None:
    bt = Backtest(
        strategy=BuyOnFirstBar(),
        bar_loader=DataFrameBarLoader(bars()),
        symbols=["000001.SZ"],
        start=datetime(2026, 1, 1, tzinfo=get_shanghai_tz()),
        end=datetime(2026, 1, 3, tzinfo=get_shanghai_tz()),
        initial_cash=Decimal("1000"),
        fee_model=CompositeFee(models=(FixedFee(Decimal("1")), PercentageFee(Decimal("0.001")))),
    )
    result = bt.run()
    # fee = 1 + 0.001 * 10 * 11 = 1 + 0.11 = 1.11
    assert result.fills[0].fee == Decimal("1.11")


def test_default_fee_slippage_zero_backward_compatible() -> None:
    """Default parameters should behave identically to P0 (zero fee/slippage)."""
    bt = Backtest(
        strategy=BuyOnFirstBar(),
        bar_loader=DataFrameBarLoader(bars()),
        symbols=["000001.SZ"],
        start=datetime(2026, 1, 1, tzinfo=get_shanghai_tz()),
        end=datetime(2026, 1, 3, tzinfo=get_shanghai_tz()),
        initial_cash=Decimal("1000"),
    )
    result = bt.run()
    assert result.fills[0].fee == Decimal("0")
    assert result.fills[0].slippage == Decimal("0")
    assert result.fills[0].price == Decimal("11")
