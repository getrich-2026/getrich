"""Tests for the portfolio construction layer."""

from datetime import datetime
from decimal import Decimal

import polars as pl
import pytest

from getrich_backtest import (
    AccountView,
    BarContext,
    Constraints,
    EqualWeight,
    HistoryView,
    PeriodicRebalance,
    Portfolio,
    PositionView,
    StrategyError,
    get_shanghai_tz,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TZ = get_shanghai_tz()


def _dummy_ctx() -> BarContext:
    """Minimal BarContext; unused by EqualWeight but required by protocol."""
    bar = pl.DataFrame(
        {
            "dt": [datetime(2026, 6, 1, 9, 30, tzinfo=TZ)],
            "symbol": ["_"],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.0],
            "volume": [1000.0],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )
    return BarContext(
        now=datetime(2026, 6, 1, 9, 30, tzinfo=TZ),
        run_id="test",
        account=AccountView(cash=Decimal("100000")),
        bar=bar,
        history=HistoryView(bar),
    )


def _scores(symbol_score_pairs: list[tuple[str, float]]) -> pl.DataFrame:
    symbols = [s for s, _ in symbol_score_pairs]
    scores = [sc for _, sc in symbol_score_pairs]
    return pl.DataFrame({"symbol": symbols, "score": scores})


def _single_bar_barctx(close_map: dict[str, float]) -> BarContext:
    """Build a minimal BarContext with one bar and empty account."""
    symbols = list(close_map.keys())
    bar = pl.DataFrame(
        {
            "dt": [datetime(2026, 6, 1, 9, 30, tzinfo=TZ)] * len(symbols),
            "symbol": symbols,
            "open": list(close_map.values()),
            "high": [v * 1.02 for v in close_map.values()],
            "low": [v * 0.98 for v in close_map.values()],
            "close": list(close_map.values()),
            "volume": [1000.0] * len(symbols),
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )
    return BarContext(
        now=datetime(2026, 6, 1, 9, 30, tzinfo=TZ),
        run_id="test",
        account=AccountView(cash=Decimal("100000")),
        bar=bar,
        history=HistoryView(bar),
    )


# ---------------------------------------------------------------------------
# EqualWeight
# ---------------------------------------------------------------------------


class TestEqualWeight:
    def test_long_only_top_k(self) -> None:
        ew = EqualWeight(top_k=3, bottom_k=0, long_only=True)
        scores = _scores([("A", 3.0), ("B", 2.0), ("C", 1.0), ("D", 0.0), ("E", -1.0)])
        result = ew.allocate(scores, _dummy_ctx())
        assert result.columns == ["symbol", "weight"]
        assert result.height == 3
        # All weights should be 1/3 ≈ 0.3333
        for row in result.iter_rows(named=True):
            assert row["weight"] == pytest.approx(1.0 / 3)

    def test_long_short(self) -> None:
        ew = EqualWeight(top_k=2, bottom_k=2, long_only=False)
        scores = _scores([("A", 5.0), ("B", 4.0), ("C", 3.0), ("D", 2.0), ("E", 1.0)])
        result = ew.allocate(scores, _dummy_ctx())
        assert result.height == 4
        longs = result.filter(pl.col("weight") > 0)
        shorts = result.filter(pl.col("weight") < 0)
        assert longs.height == 2
        assert shorts.height == 2
        for row in longs.iter_rows(named=True):
            assert row["weight"] == pytest.approx(0.5)
        for row in shorts.iter_rows(named=True):
            assert row["weight"] == pytest.approx(-0.5)

    def test_long_only_bottom_k_ignored(self) -> None:
        """When long_only=True, bottom_k should produce no short positions."""
        ew = EqualWeight(top_k=2, bottom_k=2, long_only=True)
        scores = _scores([("A", 5.0), ("B", 4.0), ("C", 3.0), ("D", 2.0)])
        result = ew.allocate(scores, _dummy_ctx())
        assert result.height == 2
        assert (result["weight"] > 0).all()

    def test_empty_when_both_k_zero(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            EqualWeight(top_k=0, bottom_k=0)

    def test_validates_negative_k(self) -> None:
        with pytest.raises(ValueError, match="top_k"):
            EqualWeight(top_k=-1, bottom_k=1)
        with pytest.raises(ValueError, match="bottom_k"):
            EqualWeight(top_k=1, bottom_k=-1)

    def test_skips_null_scores(self) -> None:
        ew = EqualWeight(top_k=2, long_only=True)
        scores = pl.DataFrame({"symbol": ["A", "B", "C"], "score": [1.0, None, 2.0]})
        result = ew.allocate(scores, _dummy_ctx())
        assert result.height == 2  # only A and C
        assert "B" not in result["symbol"]

    def test_empty_scores_returns_empty(self) -> None:
        ew = EqualWeight(top_k=2, long_only=True)
        result = ew.allocate(pl.DataFrame({"symbol": [], "score": []}), _dummy_ctx())
        assert result.is_empty()

    def test_validates_missing_columns(self) -> None:
        ew = EqualWeight(top_k=2, long_only=True)
        ctx = _dummy_ctx()
        with pytest.raises(StrategyError, match="missing required columns"):
            ew.allocate(pl.DataFrame({"x": [1, 2]}), ctx)


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------


class TestConstraints:
    def _weights(self, pairs: list[tuple[str, float]]) -> pl.DataFrame:
        return pl.DataFrame({"symbol": [s for s, _ in pairs], "weight": [w for _, w in pairs]})

    def test_max_single_weight(self) -> None:
        c = Constraints(max_single_weight=Decimal("0.3"))
        result = c.apply(self._weights([("A", 0.5), ("B", 0.2)]))
        clipped = result.filter(pl.col("symbol") == "A")["weight"].item()
        assert clipped == pytest.approx(0.3)

    def test_gross_exposure_scaling(self) -> None:
        c = Constraints(gross_exposure=Decimal("1.0"))
        result = c.apply(self._weights([("A", 0.8), ("B", 0.8)]))
        gross = result.select(pl.col("weight").abs().sum()).item()
        assert gross == pytest.approx(1.0)
        assert result["weight"].to_list() == [pytest.approx(0.5), pytest.approx(0.5)]

    def test_long_only_zeroes_negative(self) -> None:
        c = Constraints(long_only=True)
        result = c.apply(self._weights([("A", 0.5), ("B", -0.3)]))
        b_weight = result.filter(pl.col("symbol") == "B")["weight"].item()
        assert b_weight == pytest.approx(0.0)

    def test_empty_input(self) -> None:
        c = Constraints()
        result = c.apply(self._weights([]))
        assert result.is_empty()

    def test_validates_missing_columns(self) -> None:
        c = Constraints()
        with pytest.raises(StrategyError, match="missing required columns"):
            c.apply(pl.DataFrame({"x": [1]}))


# ---------------------------------------------------------------------------
# PeriodicRebalance
# ---------------------------------------------------------------------------


class TestPeriodicRebalance:
    def test_rebalances_on_first_bar(self) -> None:
        rule = PeriodicRebalance(every_n_bars=3)
        ctx = _single_bar_barctx({"A": 10.0})
        assert rule.should_rebalance(ctx, None) is True

    def test_rebalances_every_n_bars(self) -> None:
        rule = PeriodicRebalance(every_n_bars=3)
        # 4 bars in history: after excluding rebalance_dt (6/1), 3 bars remain
        dts = [datetime(2026, 6, i + 1, 9, 30, tzinfo=TZ) for i in range(4)]
        hist_bars = pl.DataFrame(
            {
                "dt": dts,
                "symbol": ["A"] * 4,
                "open": [10.0] * 4,
                "high": [11.0] * 4,
                "low": [9.0] * 4,
                "close": [10.0] * 4,
                "volume": [1000.0] * 4,
            },
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )
        ctx = _single_bar_barctx({"A": 10.0})
        object.__setattr__(ctx, "history", HistoryView(hist_bars))

        rebalance_dt = datetime(2026, 6, 1, 9, 30, tzinfo=TZ)
        assert rule.should_rebalance(ctx, rebalance_dt) is True

    def test_does_not_rebalance_too_soon(self) -> None:
        rule = PeriodicRebalance(every_n_bars=5)
        dts = [datetime(2026, 6, i + 1, 9, 30, tzinfo=TZ) for i in range(2)]
        hist_bars = pl.DataFrame(
            {
                "dt": dts,
                "symbol": ["A"] * 2,
                "open": [10.0] * 2,
                "high": [11.0] * 2,
                "low": [9.0] * 2,
                "close": [10.0] * 2,
                "volume": [1000.0] * 2,
            },
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )
        ctx = _single_bar_barctx({"A": 10.0})
        object.__setattr__(ctx, "history", HistoryView(hist_bars))

        rebalance_dt = datetime(2026, 6, 1, 9, 30, tzinfo=TZ)
        assert rule.should_rebalance(ctx, rebalance_dt) is False

    def test_rejects_invalid_period(self) -> None:
        with pytest.raises(ValueError, match=">= 1"):
            PeriodicRebalance(every_n_bars=0)


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------


class TestPortfolio:
    def test_build_orders_from_scores(self) -> None:
        pf = Portfolio(
            allocator=EqualWeight(top_k=2, long_only=True),
            constraints=Constraints(max_single_weight=Decimal("1.0")),
        )
        scores = _scores([("A", 5.0), ("B", 3.0), ("C", 1.0)])
        ctx = _single_bar_barctx({"A": 10.0, "B": 20.0, "C": 30.0})
        orders = pf.build_orders(scores, ctx)
        # top_k=2 → A (weight=0.5) and B (weight=0.5)
        # NAV = 100000
        # A: target_qty = floor(0.5 * 100000 / 10) = 5000
        # B: target_qty = floor(0.5 * 100000 / 20) = 2500
        assert len(orders) == 2
        order_map = {o.symbol: o for o in orders}
        assert order_map["A"].side.value == "BUY"
        assert order_map["A"].qty == 5000
        assert order_map["B"].side.value == "BUY"
        assert order_map["B"].qty == 2500

    def test_skips_when_rebalance_says_no(self) -> None:
        class NeverRebalance:
            def should_rebalance(self, ctx, last_rebalance_dt):
                return False

        pf = Portfolio(
            allocator=EqualWeight(top_k=2, long_only=True),
            rebalance=NeverRebalance(),
        )
        scores = _scores([("A", 5.0)])
        ctx = _single_bar_barctx({"A": 10.0})
        orders = pf.build_orders(scores, ctx)
        assert orders == []

    def test_handles_zero_nav(self) -> None:
        pf = Portfolio(allocator=EqualWeight(top_k=2, long_only=True))
        scores = _scores([("A", 5.0)])
        ctx = _single_bar_barctx({"A": 10.0})
        # Override account with zero cash
        object.__setattr__(ctx, "account", AccountView(cash=Decimal("0")))
        orders = pf.build_orders(scores, ctx)
        assert orders == []

    def test_handles_empty_scores(self) -> None:
        pf = Portfolio(allocator=EqualWeight(top_k=2, long_only=True))
        empty = pl.DataFrame({"symbol": [], "score": []})
        ctx = _single_bar_barctx({"A": 10.0})
        orders = pf.build_orders(empty, ctx)
        assert orders == []

    def test_skips_symbol_without_price(self) -> None:
        pf = Portfolio(allocator=EqualWeight(top_k=2, long_only=True))
        scores = _scores([("A", 5.0), ("B", 3.0)])
        ctx = _single_bar_barctx({"A": 10.0})  # B has no price
        orders = pf.build_orders(scores, ctx)
        # Only A should produce an order
        assert len(orders) == 1
        assert orders[0].symbol == "A"

    def test_position_is_delta(self) -> None:
        """Portfolio should only order the delta, not the full target."""
        pf = Portfolio(allocator=EqualWeight(top_k=2, long_only=True))
        scores = _scores([("A", 5.0)])
        ctx = _single_bar_barctx({"A": 10.0})
        # Already holds 3000 shares of A
        existing = {"A": PositionView(symbol="A", qty=Decimal("3000"))}
        object.__setattr__(
            ctx,
            "account",
            AccountView(cash=Decimal("50000"), positions=existing),
        )
        orders = pf.build_orders(scores, ctx)
        # top_k=2 → weight=0.5 per symbol
        # NAV = 50000 cash + 3000 * 10 = 80000
        # target_qty = floor(0.5 * 80000 / 10) = 4000
        # delta = 4000 - 3000 = 1000
        assert len(orders) == 1
        assert orders[0].qty == 1000


class TestLotSize:
    """Tests for lot_size rounding in Portfolio.build_orders()."""

    def test_lot_size_rounds_to_nearest_hundred(self) -> None:
        """Delta is rounded down to nearest 100 (default lot_size)."""
        pf = Portfolio(
            allocator=EqualWeight(top_k=2, long_only=True),
            constraints=Constraints(max_single_weight=Decimal("1.0")),
        )
        scores = _scores([("A", 5.0)])
        ctx = _single_bar_barctx({"A": 62.8})
        orders = pf.build_orders(scores, ctx)
        assert len(orders) == 1
        # target_notional = 0.5 * 100000 = 50000
        # target_qty = int(50000 // 62.8) = int(796.17...) = 796
        # delta = _round_to_lot(796 - 0, 100) = 700
        assert orders[0].qty <= 796
        assert orders[0].qty % 100 == 0  # multiple of 100

    def test_lot_size_small_delta_skipped(self) -> None:
        """Delta smaller than lot_size is skipped."""
        pf = Portfolio(
            allocator=EqualWeight(top_k=2, long_only=True),
            lot_size=500,
        )
        scores = _scores([("A", 5.0)])
        ctx = _single_bar_barctx({"A": 50000.0})
        orders = pf.build_orders(scores, ctx)
        assert orders == []

    def test_lot_size_custom_value(self) -> None:
        """Custom lot_size (10) rounds correctly."""
        pf = Portfolio(
            allocator=EqualWeight(top_k=2, long_only=True),
            lot_size=10,
        )
        scores = _scores([("A", 5.0)])
        ctx = _single_bar_barctx({"A": 33.0})
        orders = pf.build_orders(scores, ctx)
        assert len(orders) == 1
        # target_qty = int(0.5 * 100000 // 33) = 1515
        # delta = _round_to_lot(1515, 10) = 1510
        assert orders[0].qty == 1510

    def test_lot_size_negative_delta_skipped(self) -> None:
        """Negative delta smaller than lot_size is skipped."""
        pf = Portfolio(
            allocator=EqualWeight(top_k=2, long_only=True),
        )
        scores = _scores([("A", 5.0)])
        ctx = _single_bar_barctx({"A": 10.0})
        # NAV = 49500 (cash) + 5050 * 10 (position) = 100000
        # target_qty = int(0.5 * 100000 // 10) = 5000
        # delta = 5000 - 5050 = -50 → _round_to_lot(-50, 100) = 0 → skip
        existing = {"A": PositionView(symbol="A", qty=Decimal("5050"))}
        object.__setattr__(
            ctx,
            "account",
            AccountView(cash=Decimal("49500"), positions=existing),
        )
        orders = pf.build_orders(scores, ctx)
        assert orders == []

    def test_lot_size_zero_raises(self) -> None:
        """lot_size must be positive."""
        with pytest.raises(StrategyError, match="lot_size must be positive"):
            Portfolio(
                allocator=EqualWeight(top_k=2, long_only=True),
                lot_size=0,
            )

    def test_lot_size_one_disables_rounding(self) -> None:
        """lot_size=1 means no effective rounding."""
        pf = Portfolio(
            allocator=EqualWeight(top_k=2, long_only=True),
            lot_size=1,
        )
        scores = _scores([("A", 5.0)])
        ctx = _single_bar_barctx({"A": 33.0})
        orders = pf.build_orders(scores, ctx)
        assert len(orders) == 1
        # target_qty = int(0.5 * 100000 // 33) = 1515
        # delta = _round_to_lot(1515, 1) = 1515
        assert orders[0].qty == 1515
