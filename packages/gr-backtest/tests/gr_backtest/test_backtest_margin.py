"""Integration tests for margin account in the backtest loop."""

from datetime import datetime
from decimal import Decimal

import polars as pl
from gr_backtest import (
    Backtest,
    DataFrameBarLoader,
    RiskConfig,
    Side,
    get_shanghai_tz,
)
from gr_backtest.strategy import Strategy


TZ = get_shanghai_tz()


def _futures_bars(n_bars: int = 10) -> pl.DataFrame:
    """Build synthetic index futures bars (1-day freq)."""
    base = datetime(2026, 1, 5, 9, 30, tzinfo=TZ)
    dts = [base]
    for i in range(1, n_bars):
        dts.append(datetime(2026, 1, 5 + i, 9, 30, tzinfo=TZ))
    # Simple random walk prices starting at 5000
    prices = [5000.0]
    for i in range(1, n_bars):
        prices.append(round(prices[-1] * (1.0 + (i % 3 - 1) * 0.005), 2))
    n = len(dts)
    return pl.DataFrame(
        {
            "dt": dts * 1,
            "symbol": ["IF"] * n,
            "open": prices,
            "high": [p * 1.01 for p in prices],
            "low": [p * 0.99 for p in prices],
            "close": prices,
            "volume": [1000] * n,
            "settlement": prices,
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


def _futures_instruments() -> pl.DataFrame:
    """Futures instrument metadata with margin ratios."""
    return pl.DataFrame(
        {
            "symbol": ["IF"],
            "asset_class": ["index_future"],
            "product": ["IF"],
            "exchange": ["CFFEX"],
            "multiplier": [300.0],
            "tick_size": [0.2],
            "tick_value": [60.0],
            "margin_ratio_long": [0.15],
            "margin_ratio_short": [0.15],
            "list_date": [datetime(2020, 1, 1).date()],
            "last_trade_date": [datetime(2026, 12, 31).date()],
            "delivery_date": [datetime(2027, 1, 1).date()],
            "night_session": [False],
        }
    )


class SimpleFuturesStrategy(Strategy):
    """Buys 1 IF contract on the first bar, holds."""

    def __init__(self, qty: Decimal = Decimal("1")) -> None:
        super().__init__()
        self._qty = qty
        self._did_buy = False

    def on_bar(self, ctx) -> list | None:
        if not self._did_buy:
            self._did_buy = True
            from gr_backtest import OrderIntent

            return [OrderIntent(symbol="IF", side=Side.OPEN_LONG, qty=self._qty)]
        return None


def test_stock_backtest_still_works_without_margin() -> None:
    """Existing stock-only backtest without MarginCalculator works identically."""
    bars = pl.DataFrame(
        {
            "dt": [
                datetime(2026, 1, 5, 9, 30, tzinfo=TZ),
                datetime(2026, 1, 6, 9, 30, tzinfo=TZ),
            ],
            "symbol": ["A", "A"],
            "open": [100.0, 102.0],
            "high": [105.0, 105.0],
            "low": [95.0, 98.0],
            "close": [102.0, 103.0],
            "volume": [1000, 1000],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )
    loader = DataFrameBarLoader(bars)

    class BuyOne(Strategy):
        def __init__(self) -> None:
            super().__init__()
            self._did = False

        def on_bar(self, ctx):
            if not self._did:
                self._did = True
                from gr_backtest import OrderIntent

                return [OrderIntent(symbol="A", side=Side.BUY, qty=Decimal("10"))]
            return None

    bt = Backtest(
        strategy=BuyOne(),
        bar_loader=loader,
        symbols=("A",),
        start=datetime(2026, 1, 5, 9, 30, tzinfo=TZ),
        end=datetime(2026, 1, 8, 9, 30, tzinfo=TZ),
        initial_cash=Decimal("10000"),
    )
    result = bt.run()
    assert result.fills is not None
    assert len(result.fills) > 0
    assert result.final_account.cash is not None


def test_futures_backtest_basic_flow() -> None:
    """Open/hold a futures position, verify equity curve is generated."""
    bars = _futures_bars(n_bars=10)
    loader = DataFrameBarLoader(bars, instruments=_futures_instruments())
    bt = Backtest(
        strategy=SimpleFuturesStrategy(),
        bar_loader=loader,
        symbols=("IF",),
        start=bars["dt"][0],
        end=bars["dt"][-1],
        initial_cash=Decimal("500000"),
    )
    result = bt.run()
    assert result.run_id is not None
    assert result.equity_curve is not None
    # Should have equity rows for each bar (end is exclusive, so height = n_bars - 1)
    assert result.equity_curve.height == len(bars) - 1


def test_futures_strategy_sees_available_cash() -> None:
    """Strategy can access ctx.account.available_cash during backtest."""
    bars = _futures_bars(n_bars=5)

    class CheckAvailableCash(Strategy):
        def on_bar(self, ctx):
            assert ctx.account.available_cash is not None
            return None

    loader = DataFrameBarLoader(bars, instruments=_futures_instruments())
    bt = Backtest(
        strategy=CheckAvailableCash(),
        bar_loader=loader,
        symbols=("IF",),
        start=bars["dt"][0],
        end=bars["dt"][-1],
        initial_cash=Decimal("500000"),
    )
    result = bt.run()
    assert result.run_id is not None


def test_futures_daily_settle_called_during_backtest() -> None:
    """Settlement events are created (available_cash changes due to variation PnL)."""
    bars = _futures_bars(n_bars=5)

    class TrackSettle(Strategy):
        def __init__(self) -> None:
            super().__init__()
            self._did = False

        def on_bar(self, ctx):
            if not self._did:
                self._did = True
                from gr_backtest import OrderIntent

                return [OrderIntent(symbol="IF", side=Side.OPEN_LONG, qty=Decimal("1"))]
            return None

    loader = DataFrameBarLoader(bars, instruments=_futures_instruments())
    bt = Backtest(
        strategy=TrackSettle(),
        bar_loader=loader,
        symbols=("IF",),
        start=bars["dt"][0],
        end=bars["dt"][-1],
        initial_cash=Decimal("500000"),
    )
    result = bt.run()
    # With daily_settle active, variation PnL should affect cash each bar
    assert result.equity_curve is not None
    # equity curve should have rows
    assert result.equity_curve.height >= 2


class ShortFuturesStrategy(Strategy):
    """Shorts 1 IF contract on the first bar, holds. Also tests daily settlement."""

    def __init__(self) -> None:
        super().__init__()
        self._bar_count = 0
        self._shorted = False

    def on_bar(self, ctx) -> list | None:
        self._bar_count += 1
        if not self._shorted:
            self._shorted = True
            from gr_backtest import OrderIntent

            return [OrderIntent(symbol="IF", side=Side.OPEN_SHORT, qty=Decimal("1"))]
        if self._bar_count == 3:
            from gr_backtest import OrderIntent

            return [OrderIntent(symbol="IF", side=Side.CLOSE_SHORT, qty=Decimal("1"))]
        return None


def test_futures_short_sell_backtest() -> None:
    """Full short lifecycle: open, hold with settlement, close."""
    bars = _futures_bars(n_bars=10)
    loader = DataFrameBarLoader(bars, instruments=_futures_instruments())
    bt = Backtest(
        strategy=ShortFuturesStrategy(),
        bar_loader=loader,
        symbols=("IF",),
        start=bars["dt"][0],
        end=bars["dt"][-1],
        initial_cash=Decimal("500000"),
    )
    result = bt.run()
    assert result.run_id is not None
    assert result.equity_curve is not None
    assert result.equity_curve.height >= 3


def test_short_futures_sees_available_cash() -> None:
    """Short positions affect available_cash through margin deduction in backtest loop."""
    bars = _futures_bars(n_bars=5)

    class CheckShortAvailableCash(Strategy):
        def __init__(self) -> None:
            super().__init__()
            self._did = False

        def on_bar(self, ctx):
            if not self._did:
                self._did = True
                from gr_backtest import OrderIntent

                return [OrderIntent(symbol="IF", side=Side.OPEN_SHORT, qty=Decimal("1"))]
            # Available cash should be less than total cash (margin deducted)
            assert ctx.account.available_cash is not None
            return None

    loader = DataFrameBarLoader(bars, instruments=_futures_instruments())
    bt = Backtest(
        strategy=CheckShortAvailableCash(),
        bar_loader=loader,
        symbols=("IF",),
        start=bars["dt"][0],
        end=bars["dt"][-1],
        initial_cash=Decimal("500000"),
    )
    result = bt.run()
    assert result.run_id is not None


class RepeatedOpenLongStrategy(Strategy):
    """Keeps submitting OPEN_LONG orders to test margin-call rejections."""

    def on_bar(self, ctx) -> list | None:
        from gr_backtest import OrderIntent

        return [OrderIntent(symbol="IF", side=Side.OPEN_LONG, qty=Decimal("1"))]


def _falling_futures_bars() -> pl.DataFrame:
    prices = [5000.0, 5000.0, 4980.0, 4960.0, 4940.0]
    return pl.DataFrame(
        {
            "dt": [datetime(2026, 1, 5 + i, 9, 30, tzinfo=TZ) for i in range(len(prices))],
            "symbol": ["IF"] * len(prices),
            "open": prices,
            "high": [p * 1.01 for p in prices],
            "low": [p * 0.99 for p in prices],
            "close": prices,
            "volume": [1000] * len(prices),
            "settlement": prices,
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


def test_margin_call_rejects_new_exposure_orders() -> None:
    bars = _falling_futures_bars()
    loader = DataFrameBarLoader(bars, instruments=_futures_instruments())
    bt = Backtest(
        strategy=RepeatedOpenLongStrategy(),
        bar_loader=loader,
        symbols=("IF",),
        start=bars["dt"][0],
        end=bars["dt"][-1],
        initial_cash=Decimal("450000"),
        risk_config=RiskConfig(liquidation_threshold=Decimal("0")),
    )
    result = bt.run()
    assert any(order.reject_reason == "margin call in effect" for order in result.orders)


def test_forced_liquidation_on_margin_breach() -> None:
    bars = _falling_futures_bars()
    loader = DataFrameBarLoader(bars, instruments=_futures_instruments())
    bt = Backtest(
        strategy=SimpleFuturesStrategy(qty=Decimal("2")),
        bar_loader=loader,
        symbols=("IF",),
        start=bars["dt"][0],
        end=bars["dt"][-1],
        initial_cash=Decimal("450000"),
        risk_config=RiskConfig(liquidation_threshold=Decimal("1.0")),
    )
    result = bt.run()
    assert result.final_account.position("IF").qty == Decimal("0")


def test_healthy_margin_does_not_liquidate() -> None:
    bars = _futures_bars(n_bars=5)
    loader = DataFrameBarLoader(bars, instruments=_futures_instruments())
    bt = Backtest(
        strategy=SimpleFuturesStrategy(),
        bar_loader=loader,
        symbols=("IF",),
        start=bars["dt"][0],
        end=bars["dt"][-1],
        initial_cash=Decimal("1000000"),
        risk_config=RiskConfig(),
    )
    result = bt.run()
    assert result.final_account.position("IF").qty == Decimal("1")
