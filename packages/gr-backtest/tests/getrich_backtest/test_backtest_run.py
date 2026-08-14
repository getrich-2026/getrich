from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from decimal import Decimal

import polars as pl
import pytest

from getrich_backtest import (
    DEFAULT_ASHARE_SESSIONS,
    Backtest,
    BacktestError,
    BacktestResult,
    BarContext,
    DataFrameBarLoader,
    OrderIntent,
    OrderStatus,
    Side,
    Strategy,
    StrategyError,
    get_shanghai_tz,
)


def bars() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "dt": [
                datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz()),
                datetime(2026, 1, 2, 9, 30, tzinfo=get_shanghai_tz()),
                datetime(2026, 1, 3, 9, 30, tzinfo=get_shanghai_tz()),
            ],
            "symbol": ["000001.SZ", "000001.SZ", "000001.SZ"],
            "open": [Decimal("9"), Decimal("10"), Decimal("11")],
            "high": [Decimal("9.5"), Decimal("10.5"), Decimal("11.5")],
            "low": [Decimal("8.8"), Decimal("9.8"), Decimal("10.8")],
            "close": [Decimal("9.2"), Decimal("10.2"), Decimal("11.2")],
            "volume": [900.0, 1000.0, 1100.0],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


class BuyOnFirstBarStrategy(Strategy):
    def __init__(self) -> None:
        self.calls = 0
        self.observed_qty: list[Decimal] = []

    def on_bar(self, ctx: BarContext) -> Iterable[OrderIntent] | None:
        self.calls += 1
        self.observed_qty.append(ctx.account.position("000001.SZ").qty)
        if self.calls == 1:
            return [OrderIntent(symbol="000001.SZ", side=Side.BUY, qty=Decimal("10"))]
        return None


class BadStrategy(Strategy):
    def on_bar(self, ctx: BarContext) -> Iterable[OrderIntent] | None:
        return [object()]  # type: ignore[list-item]


def backtest(strategy: Strategy) -> Backtest:
    return Backtest(
        strategy=strategy,
        bar_loader=DataFrameBarLoader(bars()),
        symbols=["000001.SZ"],
        start=datetime(2026, 1, 1, tzinfo=get_shanghai_tz()),
        end=datetime(2026, 1, 4, tzinfo=get_shanghai_tz()),
        initial_cash=Decimal("1000"),
        run_id="run-1",
    )


def test_backtest_run_returns_result_and_fills_next_bar_open() -> None:
    strategy = BuyOnFirstBarStrategy()
    result = backtest(strategy).run()

    assert isinstance(result, BacktestResult)
    assert len(result.orders) == 1
    assert len(result.fills) == 1
    assert result.orders[0].status == OrderStatus.FILLED
    assert result.fills[0].price == Decimal("10")
    assert result.fills[0].bar_dt == datetime(2026, 1, 2, 9, 30, tzinfo=get_shanghai_tz())
    assert result.final_account.cash == Decimal("900")
    assert result.final_account.position("000001.SZ").qty == Decimal("10")
    assert result.equity_curve.height == 3

    ec = result.equity_curve
    assert "trading_pnl" in ec.columns
    assert "mtm_pnl" in ec.columns
    assert "total_fees" in ec.columns
    assert "gross_exposure" in ec.columns

    # Bar 0: no fills yet, no positions → all zero
    assert ec["trading_pnl"][0] == Decimal("0")
    assert ec["mtm_pnl"][0] == Decimal("0")
    assert ec["total_fees"][0] == Decimal("0")
    assert ec["gross_exposure"][0] == Decimal("0")

    # Bar 1: fill occurs (buy 10 @ 10), equity ≈ 900 + 10*10.2 = 1002
    # trading_pnl = 0 (buy doesn't realize PnL), mtm = equity_change
    assert ec["trading_pnl"][1] == Decimal("0")
    assert ec["mtm_pnl"][1] == Decimal("2")
    assert ec["total_fees"][1] == Decimal("0")
    assert ec["gross_exposure"][1] == Decimal("102")


def test_strategy_sees_position_only_after_next_bar_fill() -> None:
    strategy = BuyOnFirstBarStrategy()
    backtest(strategy).run()

    assert strategy.observed_qty == [Decimal("0"), Decimal("10"), Decimal("10")]


def test_last_bar_order_expires() -> None:
    class BuyOnLastBarStrategy(Strategy):
        def __init__(self) -> None:
            self.calls = 0

        def on_bar(self, ctx: BarContext) -> Iterable[OrderIntent] | None:
            self.calls += 1
            if self.calls == 3:
                return [OrderIntent(symbol="000001.SZ", side=Side.BUY, qty=Decimal("1"))]
            return None

    result = backtest(BuyOnLastBarStrategy()).run()
    assert result.orders[0].status == OrderStatus.EXPIRED
    assert result.fills == ()


def test_backtest_rejects_non_decimal_initial_cash() -> None:
    with pytest.raises(BacktestError, match="decimal.Decimal"):
        Backtest(
            strategy=Strategy(),
            bar_loader=DataFrameBarLoader(bars()),
            symbols=["000001.SZ"],
            start=datetime(2026, 1, 1, tzinfo=get_shanghai_tz()),
            end=datetime(2026, 1, 4, tzinfo=get_shanghai_tz()),
            initial_cash=1000.0,  # type: ignore[arg-type]
        )


def test_backtest_rejects_empty_symbols() -> None:
    with pytest.raises(BacktestError, match="symbols"):
        Backtest(
            strategy=Strategy(),
            bar_loader=DataFrameBarLoader(bars()),
            symbols=[],
            start=datetime(2026, 1, 1, tzinfo=get_shanghai_tz()),
            end=datetime(2026, 1, 4, tzinfo=get_shanghai_tz()),
            initial_cash=Decimal("1000"),
        )


def test_backtest_rejects_invalid_strategy_return() -> None:
    with pytest.raises(StrategyError, match="OrderIntent"):
        backtest(BadStrategy()).run()


# ── Multi-frequency backtest smoke tests (P10 Phase 3) ────────────────────


def _make_multi_freq_test_bars(freq: str) -> pl.DataFrame:
    """Build bars at the requested frequency for multi-freq testing."""
    tz = get_shanghai_tz()
    rows = []
    for day in range(1, 3):
        if freq == "5m":
            for m in range(2):
                dt = datetime(2026, 1, day, 9, 30 + m * 5, 0, tzinfo=tz)
                rows.append(
                    {
                        "dt": dt,
                        "symbol": "000001.SZ",
                        "open": Decimal("10"),
                        "high": Decimal("11"),
                        "low": Decimal("9"),
                        "close": Decimal("10.5"),
                        "volume": 1000.0,
                    }
                )
        elif freq == "1d":
            dt = datetime(2026, 1, day, 9, 30, 0, tzinfo=tz)
            rows.append(
                {
                    "dt": dt,
                    "symbol": "000001.SZ",
                    "open": Decimal("10"),
                    "high": Decimal("11"),
                    "low": Decimal("9"),
                    "close": Decimal("10.5"),
                    "volume": 1000.0,
                }
            )
    return pl.DataFrame(
        rows,
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


class _MultiFreqTestLoader:
    """Minimal loader that returns per-frequency DataFrames."""

    def __init__(self, bars_by_freq: dict[str, pl.DataFrame]) -> None:
        self._bars = bars_by_freq

    def load_bars(
        self,
        symbols: Sequence[str] | None,
        start: datetime,
        end: datetime,
        freq: str = "1d",
    ) -> pl.DataFrame:
        return self._bars.get(freq, pl.DataFrame())


def _make_session_1m_bars() -> pl.DataFrame:
    """Build 1m bars that start at the A-share open boundary."""
    tz = get_shanghai_tz()
    rows = []
    for i in range(60):
        dt = datetime(2026, 1, 1, 9, 30, tzinfo=tz) + timedelta(minutes=i)
        rows.append(
            {
                "dt": dt,
                "symbol": "000001.SZ",
                "open": Decimal("10"),
                "high": Decimal("11"),
                "low": Decimal("9"),
                "close": Decimal("10.5"),
                "volume": 1000.0,
            }
        )
    return pl.DataFrame(
        rows,
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


class MultiFreqAccessStrategy(Strategy):
    """Strategy that verifies extra_history is accessible."""

    def __init__(self) -> None:
        self.extra_history_accessed = False

    def on_bar(self, ctx: BarContext) -> Iterable[OrderIntent] | None:
        if ctx.extra_history is not None:
            self.extra_history_accessed = True
            daily = ctx.extra_history.get("1d")
            if daily is not None:
                daily.lookback(n=1)
        return None


def test_backtest_run_with_5m_primary_1d_extra() -> None:
    """Full smoke test: 5m primary, 1d extra, strategy accesses both."""
    bars_by_freq = {
        "5m": _make_multi_freq_test_bars("5m"),
        "1d": _make_multi_freq_test_bars("1d"),
    }
    strategy = MultiFreqAccessStrategy()
    bt = Backtest(
        strategy=strategy,
        bar_loader=_MultiFreqTestLoader(bars_by_freq),  # type: ignore[arg-type]
        symbols=["000001.SZ"],
        start=datetime(2026, 1, 1, tzinfo=get_shanghai_tz()),
        end=datetime(2026, 1, 3, tzinfo=get_shanghai_tz()),
        initial_cash=Decimal("1000"),
        freq="5m",
        extra_freqs=["1d"],
        run_id="multi-freq-test",
    )
    result = bt.run()
    assert isinstance(result, BacktestResult)
    assert strategy.extra_history_accessed


class SessionExtraFreqStrategy(Strategy):
    """Strategy that records the first session-aligned extra bar timestamp."""

    def __init__(self) -> None:
        self.first_extra_dt: datetime | None = None

    def on_bar(self, ctx: BarContext) -> Iterable[OrderIntent] | None:
        if ctx.extra_history is not None and self.first_extra_dt is None:
            extra = ctx.extra_history["1h"].bars
            if extra.height > 0:
                self.first_extra_dt = extra["dt"][0]
        return None


def test_backtest_extra_bars_can_be_session_aligned() -> None:
    """sessions= makes extra_freqs align to 09:30 instead of wall-clock 09:00."""
    strategy = SessionExtraFreqStrategy()
    bt = Backtest(
        strategy=strategy,
        bar_loader=DataFrameBarLoader(_make_session_1m_bars()),
        symbols=["000001.SZ"],
        start=datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz()),
        end=datetime(2026, 1, 1, 10, 30, tzinfo=get_shanghai_tz()),
        initial_cash=Decimal("1000"),
        freq="1m",
        extra_freqs=["1h"],
        sessions=DEFAULT_ASHARE_SESSIONS,
        run_id="session-extra-test",
    )

    result = bt.run()

    assert strategy.first_extra_dt == datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz())
    assert result.extra_bars is not None
    assert result.extra_bars["1h"]["dt"][0] == datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz())


def test_backtest_extra_bars_in_result() -> None:
    """result.extra_bars contains the extra freq DataFrames."""
    bars_by_freq = {
        "5m": _make_multi_freq_test_bars("5m"),
        "1d": _make_multi_freq_test_bars("1d"),
    }
    strategy = Strategy()
    bt = Backtest(
        strategy=strategy,
        bar_loader=_MultiFreqTestLoader(bars_by_freq),  # type: ignore[arg-type]
        symbols=["000001.SZ"],
        start=datetime(2026, 1, 1, tzinfo=get_shanghai_tz()),
        end=datetime(2026, 1, 3, tzinfo=get_shanghai_tz()),
        initial_cash=Decimal("1000"),
        freq="5m",
        extra_freqs=["1d"],
        run_id="extra-bars-test",
    )
    result = bt.run()
    assert result.extra_bars is not None
    assert set(result.extra_bars.keys()) == {"1d"}
    assert result.extra_bars["1d"].height > 0
