"""Tests for TargetPositionStrategy."""

from datetime import datetime
from decimal import Decimal

import polars as pl
import pytest

from getrich_backtest import (
    AccountView,
    Backtest,
    BarContext,
    DataFrameBarLoader,
    HistoryView,
    StrategyError,
    get_shanghai_tz,
)
from getrich_backtest.strategy.target_position import TargetPositionStrategy


TZ = get_shanghai_tz()


def _bar_ctx(
    cash: Decimal = Decimal("100000"),
    positions: dict[str, Decimal] | None = None,
) -> BarContext:
    # We need to build AccountView with proper positions
    from getrich_backtest import PositionView  # noqa: F811

    pos_dict = {s: PositionView(symbol=s, qty=q) for s, q in (positions or {}).items()}
    bar = pl.DataFrame(
        {
            "dt": [datetime(2026, 6, 1, 9, 30, tzinfo=TZ)],
            "symbol": ["A"],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.0],
            "volume": [1000.0],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )
    return BarContext(
        now=datetime(2026, 6, 1, 9, 30, tzinfo=TZ),
        run_id="test",
        account=AccountView(cash=cash, positions=pos_dict),
        bar=bar,
        history=HistoryView(bar),
    )


def _two_bar_backtest(symbols: list[str], strategy: TargetPositionStrategy) -> Backtest:
    """Two bars of data so orders placed at bar 0 can fill at bar 1."""
    rows = []
    for i in range(2):
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
    df = pl.DataFrame(rows, schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")})
    return Backtest(
        strategy=strategy,
        bar_loader=DataFrameBarLoader(df),
        symbols=symbols,
        start=datetime(2026, 6, 1, tzinfo=TZ),
        end=datetime(2026, 6, 3, tzinfo=TZ),
        initial_cash=Decimal("100000"),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_target_qty_buy_signal() -> None:
    """target_qty > current_qty → BUY order."""

    class BuyTarget(TargetPositionStrategy):
        def compute_target(self, ctx):
            return pl.DataFrame({"symbol": ["A"], "target_qty": [Decimal("100")]})

    ctx = _bar_ctx()
    intents = list(BuyTarget().on_bar(ctx))
    assert len(intents) == 1
    assert intents[0].symbol == "A"
    assert intents[0].side.value == "BUY"
    assert intents[0].qty == 100


def test_target_qty_sell_signal() -> None:
    """target_qty < current_qty → SELL order."""

    class SellTarget(TargetPositionStrategy):
        def compute_target(self, ctx):
            return pl.DataFrame({"symbol": ["A"], "target_qty": [Decimal("50")]})

    ctx = _bar_ctx(positions={"A": Decimal("200")})
    intents = list(SellTarget().on_bar(ctx) or [])
    assert len(intents) == 1
    assert intents[0].side.value == "SELL"
    assert intents[0].qty == 150


def test_target_qty_no_change() -> None:
    """target_qty == current_qty → no orders."""

    class NoChange(TargetPositionStrategy):
        def compute_target(self, ctx):
            return pl.DataFrame({"symbol": ["A"], "target_qty": [Decimal("100")]})

    ctx = _bar_ctx(positions={"A": Decimal("100")})
    result = NoChange().on_bar(ctx)
    assert result == []


def test_target_weight_generates_buy() -> None:
    """target_weight > 0 → BUY with correct qty."""

    class WeightTarget(TargetPositionStrategy):
        def compute_target(self, ctx):
            return pl.DataFrame({"symbol": ["A"], "target_weight": [Decimal("0.5")]})

    # NAV = 100000 cash + 0 position value = 100000
    # target_qty = floor(0.5 * 100000 / 10) = 5000
    ctx = _bar_ctx(cash=Decimal("100000"))
    intents = list(WeightTarget().on_bar(ctx) or [])
    assert len(intents) == 1
    assert intents[0].side.value == "BUY"
    assert intents[0].qty == 5000


def test_target_weight_delta() -> None:
    """target_weight with existing position → only delta."""

    class WeightDelta(TargetPositionStrategy):
        def compute_target(self, ctx):
            return pl.DataFrame({"symbol": ["A"], "target_weight": [Decimal("0.5")]})

    # Already holds 2000 shares of A
    # NAV = 80000 cash + 2000 * 10 = 100000
    # target_qty = floor(0.5 * 100000 / 10) = 5000
    # delta = 5000 - 2000 = 3000
    ctx = _bar_ctx(cash=Decimal("80000"), positions={"A": Decimal("2000")})
    intents = list(WeightDelta().on_bar(ctx) or [])
    assert len(intents) == 1
    assert intents[0].qty == 3000


def test_requires_column() -> None:
    """compute_target must return target_qty or target_weight."""

    class BadTarget(TargetPositionStrategy):
        def compute_target(self, ctx):
            return pl.DataFrame({"symbol": ["A"], "something_else": [1]})

    ctx = _bar_ctx()
    with pytest.raises(StrategyError, match="target_qty.*target_weight"):
        BadTarget().on_bar(ctx)


def test_not_implemented() -> None:
    strat = TargetPositionStrategy()
    with pytest.raises(NotImplementedError, match="compute_target"):
        strat.compute_target(None)  # type: ignore[arg-type]


def test_empty_target_returns_none() -> None:
    class EmptyTarget(TargetPositionStrategy):
        def compute_target(self, ctx):
            return pl.DataFrame({"symbol": [], "target_qty": []})

    result = EmptyTarget().on_bar(_bar_ctx())
    assert result is None


def test_integration_via_backtest_run() -> None:
    """End-to-end: TargetPositionStrategy through Backtest.run()."""

    class FixedTargetStrat(TargetPositionStrategy):
        def compute_target(self, ctx):
            return pl.DataFrame({"symbol": ["A"], "target_qty": [Decimal("100")]})

    bt = _two_bar_backtest(["A"], FixedTargetStrat())
    result = bt.run()
    assert len(result.fills) == 1
    fill = result.fills[0]
    assert fill.symbol == "A"
    assert fill.side.value == "BUY"
    assert fill.qty == 100


def _make_barctx(
    cash: Decimal = Decimal("100000"),
    positions: dict[str, Decimal] | None = None,
    close_price: float = 33.0,
) -> BarContext:
    """Create a BarContext with a configurable close price."""
    from getrich_backtest import PositionView  # noqa: F811

    pos_dict = {s: PositionView(symbol=s, qty=q) for s, q in (positions or {}).items()}
    bar = pl.DataFrame(
        {
            "dt": [datetime(2026, 6, 1, 9, 30, tzinfo=TZ)],
            "symbol": ["A"],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [close_price],
            "volume": [1000.0],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )
    return BarContext(
        now=datetime(2026, 6, 1, 9, 30, tzinfo=TZ),
        run_id="test",
        account=AccountView(cash=cash, positions=pos_dict),
        bar=bar,
        history=HistoryView(bar),
    )


class TestTargetLotSize:
    """Tests for lot_size rounding in TargetPositionStrategy."""

    def test_target_weight_lot_rounding(self) -> None:
        """Weight-based target rounds qty to nearest lot."""

        class WeightTarget(TargetPositionStrategy):
            def compute_target(self, ctx):
                return pl.DataFrame({"symbol": ["A"], "target_weight": [Decimal("0.5")]})

        strat = WeightTarget()
        ctx = _make_barctx(cash=Decimal("100000"))
        intents = list(strat.on_bar(ctx) or [])
        assert len(intents) == 1
        # target_qty = int(0.5 * 100000 // 33) = 1515
        # delta = _round_to_lot(1515, 100) = 1500
        assert intents[0].qty == 1500
        assert intents[0].qty % 100 == 0

    def test_target_weight_custom_lot_size(self) -> None:
        """Custom lot_size (10) works."""

        class WeightTarget10(TargetPositionStrategy):
            def __init__(self) -> None:
                super().__init__(lot_size=10)

            def compute_target(self, ctx):
                return pl.DataFrame({"symbol": ["A"], "target_weight": [Decimal("0.5")]})

        strat = WeightTarget10()
        ctx = _make_barctx(cash=Decimal("100000"))
        intents = list(strat.on_bar(ctx) or [])
        assert len(intents) == 1
        assert intents[0].qty == 1510

    def test_target_weight_small_delta_skipped(self) -> None:
        """Delta < lot_size -> no order."""

        class SmallWeight(TargetPositionStrategy):
            def __init__(self) -> None:
                super().__init__(lot_size=500)

            def compute_target(self, ctx):
                return pl.DataFrame({"symbol": ["A"], "target_weight": [Decimal("0.01")]})

        strat = SmallWeight()
        ctx = _make_barctx(cash=Decimal("100000"))
        intents = list(strat.on_bar(ctx) or [])
        # target_qty = int(0.01 * 100000 // 33) = int(30.30) = 30
        # delta = _round_to_lot(30, 500) = 0 → skip
        assert intents == []
