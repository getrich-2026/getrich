"""Integration tests for multi-strategy backtest runs."""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

import polars as pl
import pytest

from getrich_backtest import (
    Backtest,
    BacktestError,
    BacktestResult,
    BarContext,
    CombinedResult,
    DataFrameBarLoader,
    OrderIntent,
    ResultView,
    Side,
    Strategy,
    get_shanghai_tz,
)


TZ = get_shanghai_tz()


class BuyOne(Strategy):
    """Buys 1 share on the first bar, does nothing else."""

    def __init__(self, name: str | None = None, symbol: str = "A") -> None:
        self._name = name
        self._symbol = symbol
        self._fired = False

    @property
    def name(self) -> str:
        return self._name or self.__class__.__name__

    def on_bar(self, ctx: BarContext) -> list[OrderIntent] | None:
        if not self._fired:
            self._fired = True
            return [OrderIntent(symbol=self._symbol, side=Side.BUY, qty=Decimal("1"))]
        return None


def _bars_2d(symbols: list[str] | None = None) -> pl.DataFrame:
    if symbols is None:
        symbols = ["A"]
    rows = []
    for i in range(3):
        for sym in symbols:
            rows.append(
                {
                    "dt": datetime(2026, 6, i + 1, 9, 30, tzinfo=TZ),
                    "symbol": sym,
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.0,
                    "close": 10.0,
                    "volume": 1000.0,
                }
            )
    return pl.DataFrame(rows, schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")})


def _bars_multi_freq(freq: str, symbols: list[str] | None = None) -> pl.DataFrame:
    if symbols is None:
        symbols = ["A"]
    rows = []
    for day in range(1, 3):
        dts = [datetime(2026, 6, day, 9, 30, tzinfo=TZ)]
        if freq == "5m":
            dts.append(datetime(2026, 6, day, 9, 35, tzinfo=TZ))
        elif freq != "1d":
            raise ValueError(f"unsupported test freq: {freq}")
        for dt in dts:
            for sym in symbols:
                rows.append(
                    {
                        "dt": dt,
                        "symbol": sym,
                        "open": 10.0,
                        "high": 11.0,
                        "low": 9.0,
                        "close": 10.0,
                        "volume": 1000.0,
                    }
                )
    return pl.DataFrame(rows, schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")})


class _MultiFreqLoader:
    """Minimal loader that returns pre-built bars by frequency."""

    def __init__(self, bars_by_freq: dict[str, pl.DataFrame]) -> None:
        self._bars_by_freq = bars_by_freq

    def load_bars(
        self,
        symbols: Sequence[str] | None,
        start: datetime,
        end: datetime,
        freq: str = "1d",
    ) -> pl.DataFrame:
        return self._bars_by_freq.get(freq, pl.DataFrame())


class CountingStrategy(Strategy):
    """Records each on_bar call and the context shape."""

    def __init__(self, name: str, freq: str | None = None) -> None:
        self._name = name
        self.call_dts: list[datetime] = []
        self.bar_dts: list[list[datetime]] = []
        self.history_dt_counts: list[int] = []
        self.extra_history_keys: list[list[str]] = []
        if freq is not None:
            self.freq = freq

    @property
    def name(self) -> str:
        return self._name

    def on_bar(self, ctx: BarContext) -> None:
        self.call_dts.append(ctx.now)
        self.bar_dts.append(ctx.bar.select(pl.col("dt").unique().sort())["dt"].to_list())
        self.history_dt_counts.append(ctx.history.bars["dt"].n_unique())
        keys = sorted(ctx.extra_history.keys()) if ctx.extra_history else []
        self.extra_history_keys.append(keys)


class ClassDailyCountingStrategy(CountingStrategy):
    freq = "1d"

    def __init__(self, name: str) -> None:
        super().__init__(name)


class BuyOnEveryCallStrategy(CountingStrategy):
    def on_bar(self, ctx: BarContext) -> list[OrderIntent]:
        super().on_bar(ctx)
        return [OrderIntent(symbol="A", side=Side.BUY, qty=Decimal("1"))]


class BuyOnFirstCallStrategy(CountingStrategy):
    def __init__(self, name: str, freq: str | None = None) -> None:
        super().__init__(name, freq)
        self._fired = False

    def on_bar(self, ctx: BarContext) -> list[OrderIntent] | None:
        super().on_bar(ctx)
        if self._fired:
            return None
        self._fired = True
        return [OrderIntent(symbol="A", side=Side.BUY, qty=Decimal("1"))]


# ---------------------------------------------------------------------------
# Multi-strategy tests
# ---------------------------------------------------------------------------


class TestMultiStrategy:
    def test_two_strategies_return_combined_result(self) -> None:
        bt = Backtest(
            bar_loader=DataFrameBarLoader(_bars_2d()),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),
            initial_cash=Decimal("100000"),
        )
        bt.add_strategy(BuyOne("StratA"), capital_weight=Decimal("0.6"))
        bt.add_strategy(BuyOne("StratB"), capital_weight=Decimal("0.4"))
        result = bt.run()
        assert isinstance(result, CombinedResult)
        assert isinstance(result, BacktestResult)

    def test_capital_allocation_is_isolated(self) -> None:
        """Each strategy has its own account with proportional cash."""
        bt = Backtest(
            bar_loader=DataFrameBarLoader(_bars_2d()),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),
            initial_cash=Decimal("1000"),
        )
        bt.add_strategy(BuyOne("StratA"), capital_weight=Decimal("0.6"))
        bt.add_strategy(BuyOne("StratB"), capital_weight=Decimal("0.4"))
        result = bt.run()
        view_a = result.strategy("StratA")
        assert view_a is not None
        # Combined initial cash should be 1000
        assert result.initial_cash == Decimal("1000")

    def test_strategy_view_filters_fills(self) -> None:
        bt = Backtest(
            bar_loader=DataFrameBarLoader(_bars_2d()),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),
            initial_cash=Decimal("100000"),
        )
        bt.add_strategy(BuyOne("StratA"), capital_weight=Decimal("0.6"))
        bt.add_strategy(BuyOne("StratB"), capital_weight=Decimal("0.4"))
        result = bt.run()
        view_a = result.strategy("StratA")
        fills = view_a.fills
        assert len(fills) == 1  # each BuyOne fires once
        assert all(f.strategy_name == "StratA" for f in fills)

    def test_combined_view_aggregates(self) -> None:
        bt = Backtest(
            bar_loader=DataFrameBarLoader(_bars_2d()),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),
            initial_cash=Decimal("100000"),
        )
        bt.add_strategy(BuyOne("StratA"), capital_weight=Decimal("0.6"))
        bt.add_strategy(BuyOne("StratB"), capital_weight=Decimal("0.4"))
        result = bt.run()
        combined = result.combined
        assert isinstance(combined, ResultView)
        # Combined fills = both strategies' fills
        assert len(combined.fills) == 2
        ec = combined.equity_curve
        assert "strategy_name" in ec.columns

    def test_strategy_view_has_per_strategy_initial_cash(self) -> None:
        bt = Backtest(
            bar_loader=DataFrameBarLoader(_bars_2d()),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),
            initial_cash=Decimal("1000"),
        )
        bt.add_strategy(BuyOne("StratA"), capital_weight=Decimal("0.6"))
        bt.add_strategy(BuyOne("StratB"), capital_weight=Decimal("0.4"))
        result = bt.run()
        strat_a = result.strategy("StratA")
        # 1000 * 0.6 = 600, rounded down
        assert strat_a.initial_cash <= Decimal("600")

    def test_unknown_strategy_name_raises(self) -> None:
        bt = Backtest(
            bar_loader=DataFrameBarLoader(_bars_2d()),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),
            initial_cash=Decimal("1000"),
        )
        bt.add_strategy(BuyOne("StratA"))
        bt.add_strategy(BuyOne("StratB"))
        result = bt.run()
        with pytest.raises(KeyError, match="NonExistent"):
            result.strategy("NonExistent")

    def test_zero_weight_raises(self) -> None:
        bt = Backtest(
            bar_loader=DataFrameBarLoader(_bars_2d()),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),
            initial_cash=Decimal("1000"),
        )
        with pytest.raises(BacktestError, match="positive"):
            bt.add_strategy(BuyOne("A"), capital_weight=Decimal("0"))

    def test_duplicate_name_raises(self) -> None:
        bt = Backtest(
            bar_loader=DataFrameBarLoader(_bars_2d()),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),
            initial_cash=Decimal("1000"),
        )
        bt.add_strategy(BuyOne("StratX"))
        with pytest.raises(BacktestError, match="already exists"):
            bt.add_strategy(BuyOne("StratX"))

    def test_no_strategy_raises(self) -> None:
        bt = Backtest(
            bar_loader=DataFrameBarLoader(_bars_2d()),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),
            initial_cash=Decimal("1000"),
        )
        with pytest.raises(BacktestError, match="at least one"):
            bt.run()

    def test_single_via_add_strategy(self) -> None:
        """Single strategy via add_strategy still produces regular BacktestResult."""
        bt = Backtest(
            bar_loader=DataFrameBarLoader(_bars_2d()),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),
            initial_cash=Decimal("1000"),
        )
        bt.add_strategy(BuyOne("A"))
        result = bt.run()
        assert isinstance(result, BacktestResult)
        assert not isinstance(result, CombinedResult)

    def test_single_via_init(self) -> None:
        """Strategy passed via __init__ produces regular BacktestResult."""
        bt = Backtest(
            strategy=BuyOne("MyStrat"),
            bar_loader=DataFrameBarLoader(_bars_2d()),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),
            initial_cash=Decimal("1000"),
        )
        result = bt.run()
        assert isinstance(result, BacktestResult)
        assert result.strategy_name == "MyStrat"
        assert len(result.fills) == 1

    def test_init_plus_add_strategy(self) -> None:
        """__init__ strategy + add_strategy both go through multi-strategy path."""
        bt = Backtest(
            strategy=BuyOne("StratA"),
            bar_loader=DataFrameBarLoader(_bars_2d(["A", "B"])),
            symbols=["A", "B"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),
            initial_cash=Decimal("1000"),
        )
        bt.add_strategy(BuyOne("StratB"))
        result = bt.run()
        # Two strategies -> CombinedResult
        assert isinstance(result, CombinedResult)

    def test_combined_equity_curve_has_strategy_column(self) -> None:
        bt = Backtest(
            bar_loader=DataFrameBarLoader(_bars_2d()),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),
            initial_cash=Decimal("1000"),
        )
        bt.add_strategy(BuyOne("StratA"), capital_weight=Decimal("0.5"))
        bt.add_strategy(BuyOne("StratB"), capital_weight=Decimal("0.5"))
        result = bt.run()
        ec = result.combined.equity_curve
        assert "strategy_name" in ec.columns
        # Both strategys must appear
        assert ec["strategy_name"].n_unique() == 2

    def test_mixed_frequency_config_and_result_shape(self) -> None:
        fast = CountingStrategy("Fast", freq="5m")
        slow = CountingStrategy("Slow", freq="1d")
        bt = Backtest(
            bar_loader=_MultiFreqLoader(
                {"5m": _bars_multi_freq("5m"), "1d": _bars_multi_freq("1d")}
            ),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),
            initial_cash=Decimal("1000"),
            freq="1d",
        )
        bt.add_strategy(fast)
        bt.add_strategy(slow)

        result = bt.run()

        assert isinstance(result, CombinedResult)
        assert result.config.freq == "5m"
        assert result.config.strategy_freqs == (("Fast", "5m"), ("Slow", "1d"))
        assert result.strategy("Fast") is not None
        assert result.strategy("Slow") is not None

    def test_strategy_default_freq_inherits_backtest_freq(self) -> None:
        strat_a = CountingStrategy("A")
        strat_b = CountingStrategy("B")
        bt = Backtest(
            bar_loader=DataFrameBarLoader(_bars_2d()),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 4, tzinfo=TZ),
            initial_cash=Decimal("1000"),
            freq="1d",
        )
        bt.add_strategy(strat_a)
        bt.add_strategy(strat_b)

        result = bt.run()

        assert result.config.strategy_freqs == (("A", "1d"), ("B", "1d"))
        assert len(strat_a.call_dts) == 3
        assert len(strat_b.call_dts) == 3

    def test_class_attribute_freq_override(self) -> None:
        fast = CountingStrategy("Fast", freq="5m")
        slow = ClassDailyCountingStrategy("Slow")
        bt = Backtest(
            bar_loader=_MultiFreqLoader(
                {"5m": _bars_multi_freq("5m"), "1d": _bars_multi_freq("1d")}
            ),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),
            initial_cash=Decimal("1000"),
            freq="5m",
        )
        bt.add_strategy(fast)
        bt.add_strategy(slow)

        bt.run()

        assert len(fast.call_dts) == 4
        assert len(slow.call_dts) == 2
        assert slow.call_dts == [
            datetime(2026, 6, 1, 9, 30, tzinfo=TZ),
            datetime(2026, 6, 2, 9, 30, tzinfo=TZ),
        ]

    def test_instance_attribute_freq_override(self) -> None:
        fast = CountingStrategy("Fast", freq="5m")
        inherited = CountingStrategy("Inherited")
        bt = Backtest(
            bar_loader=_MultiFreqLoader(
                {"5m": _bars_multi_freq("5m"), "1d": _bars_multi_freq("1d")}
            ),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),
            initial_cash=Decimal("1000"),
            freq="1d",
        )
        bt.add_strategy(fast)
        bt.add_strategy(inherited)

        result = bt.run()

        assert result.config.freq == "5m"
        assert result.config.strategy_freqs == (("Fast", "5m"), ("Inherited", "1d"))
        assert len(fast.call_dts) == 4
        assert len(inherited.call_dts) == 2

    def test_mixed_frequency_on_bar_gating(self) -> None:
        fast = CountingStrategy("Fast", freq="5m")
        slow = CountingStrategy("Slow", freq="1d")
        bt = Backtest(
            bar_loader=_MultiFreqLoader(
                {"5m": _bars_multi_freq("5m"), "1d": _bars_multi_freq("1d")}
            ),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),
            initial_cash=Decimal("1000"),
            freq="1d",
        )
        bt.add_strategy(fast)
        bt.add_strategy(slow)

        bt.run()

        assert fast.call_dts == [
            datetime(2026, 6, 1, 9, 30, tzinfo=TZ),
            datetime(2026, 6, 1, 9, 35, tzinfo=TZ),
            datetime(2026, 6, 2, 9, 30, tzinfo=TZ),
            datetime(2026, 6, 2, 9, 35, tzinfo=TZ),
        ]
        assert slow.call_dts == [
            datetime(2026, 6, 1, 9, 30, tzinfo=TZ),
            datetime(2026, 6, 2, 9, 30, tzinfo=TZ),
        ]

    def test_strategy_context_uses_strategy_frequency(self) -> None:
        fast = CountingStrategy("Fast", freq="5m")
        slow = CountingStrategy("Slow", freq="1d")
        bt = Backtest(
            bar_loader=_MultiFreqLoader(
                {"5m": _bars_multi_freq("5m"), "1d": _bars_multi_freq("1d")}
            ),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),
            initial_cash=Decimal("1000"),
            freq="1d",
        )
        bt.add_strategy(fast)
        bt.add_strategy(slow)

        result = bt.run()

        assert fast.history_dt_counts == [1, 2, 3, 4]
        assert slow.history_dt_counts == [1, 2]
        assert fast.bar_dts[1] == [datetime(2026, 6, 1, 9, 35, tzinfo=TZ)]
        assert slow.bar_dts[-1] == [datetime(2026, 6, 2, 9, 30, tzinfo=TZ)]
        assert result.strategy("Fast").result.bars["dt"].n_unique() == 4
        assert result.strategy("Slow").result.bars["dt"].n_unique() == 2

    def test_slower_strategy_order_matches_at_base_frequency(self) -> None:
        fast = CountingStrategy("Fast", freq="5m")
        slow = BuyOnFirstCallStrategy("Slow", freq="1d")
        bt = Backtest(
            bar_loader=_MultiFreqLoader(
                {"5m": _bars_multi_freq("5m"), "1d": _bars_multi_freq("1d")}
            ),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),
            initial_cash=Decimal("1000"),
            freq="1d",
        )
        bt.add_strategy(fast)
        bt.add_strategy(slow)

        result = bt.run()
        slow_view = result.strategy("Slow")

        assert len(slow_view.orders) == 1
        assert slow_view.orders[0].created_index == 0
        assert slow_view.orders[0].eligible_index == 1
        assert len(slow_view.fills) == 1
        assert slow_view.fills[0].bar_dt == datetime(2026, 6, 1, 9, 35, tzinfo=TZ)

    def test_equity_rows_for_every_base_frequency_bar(self) -> None:
        fast = CountingStrategy("Fast", freq="5m")
        slow = CountingStrategy("Slow", freq="1d")
        bt = Backtest(
            bar_loader=_MultiFreqLoader(
                {"5m": _bars_multi_freq("5m"), "1d": _bars_multi_freq("1d")}
            ),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),
            initial_cash=Decimal("1000"),
            freq="1d",
        )
        bt.add_strategy(fast)
        bt.add_strategy(slow)

        result = bt.run()

        fast_equity = result.strategy("Fast").equity_curve
        slow_equity = result.strategy("Slow").equity_curve
        assert fast_equity.height == 4
        assert slow_equity.height == 4
        assert {"cash", "equity"}.issubset(set(slow_equity.columns))
        assert len(slow.call_dts) == 2

    def test_strategy_extra_history_filtered_by_strategy_frequency(self) -> None:
        fast = CountingStrategy("Fast", freq="5m")
        slow = CountingStrategy("Slow", freq="1d")
        bt = Backtest(
            bar_loader=_MultiFreqLoader(
                {"5m": _bars_multi_freq("5m"), "1d": _bars_multi_freq("1d")}
            ),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),
            initial_cash=Decimal("1000"),
            freq="5m",
            extra_freqs=["1d"],
        )
        bt.add_strategy(fast)
        bt.add_strategy(slow)

        result = bt.run()

        assert fast.extra_history_keys
        assert all(keys == ["1d"] for keys in fast.extra_history_keys)
        assert slow.extra_history_keys == [[], []]
        assert "1d" in (result.strategy("Fast").result.extra_bars or {})
        assert result.strategy("Slow").result.extra_bars is None

    def test_invalid_strategy_freq_raises(self) -> None:
        invalid = CountingStrategy("Invalid", freq="2m")
        other = CountingStrategy("Other", freq="1d")
        bt = Backtest(
            bar_loader=DataFrameBarLoader(_bars_2d()),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),
            initial_cash=Decimal("1000"),
        )
        bt.add_strategy(invalid)
        bt.add_strategy(other)

        with pytest.raises(BacktestError, match="invalid freq"):
            bt.run()

    def test_multi_frequency_orders_remain_strategy_scoped(self) -> None:
        fast = BuyOnEveryCallStrategy("Fast", freq="5m")
        slow = BuyOnFirstCallStrategy("Slow", freq="1d")
        bt = Backtest(
            bar_loader=_MultiFreqLoader(
                {"5m": _bars_multi_freq("5m"), "1d": _bars_multi_freq("1d")}
            ),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),
            initial_cash=Decimal("1000"),
            freq="1d",
        )
        bt.add_strategy(fast)
        bt.add_strategy(slow)

        result = bt.run()

        assert len(result.strategy("Fast").orders) == 4
        assert len(result.strategy("Slow").orders) == 1
        assert len(result.combined.orders) == 5
        assert {order.strategy_name for order in result.combined.orders} == {"Fast", "Slow"}
