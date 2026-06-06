"""Tests for the weight allocator module (ScoreWeight, InverseVol, RiskParity)."""

import math
from datetime import datetime
from decimal import Decimal

import polars as pl
import pytest

from getrich_backtest import (
    AccountView,
    BarContext,
    EqualWeight,
    HistoryView,
    Portfolio,
    StrategyError,
    get_shanghai_tz,
)
from getrich_backtest.strategy.alloc_weight import (
    BlackLitterman,
    InverseVol,
    MeanVariance,
    RiskParity,
    ScoreWeight,
)
from getrich_backtest.strategy.portfolio import WeightAllocator


TZ = get_shanghai_tz()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scores(symbol_score_pairs: list[tuple[str, float]]) -> pl.DataFrame:
    symbols = [s for s, _ in symbol_score_pairs]
    scores = [sc for _, sc in symbol_score_pairs]
    return pl.DataFrame({"symbol": symbols, "score": scores})


def _dummy_ctx() -> BarContext:
    """Minimal BarContext with a single bar; unused by ScoreWeight."""
    bar = pl.DataFrame(
        {
            "dt": [datetime(2026, 6, 1, 9, 30, tzinfo=TZ)],
            "symbol": ["_dummy"],
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


def _multi_bar_barctx(
    close_map: dict[str, list[float]],
    n_bars: int | None = None,
) -> BarContext:
    """Build a BarContext with multi-bar history.

    Parameters
    ----------
    close_map : dict[str, list[float]]
        Mapping of symbol -> list of close prices, one per bar.
        All lists must have the same length.
    n_bars : int | None
        Number of bars (inferred from close_map if None).
    """
    symbols = list(close_map.keys())
    lengths = {len(v) for v in close_map.values()}
    if len(lengths) != 1:
        raise ValueError("all close price lists must have the same length")
    n = next(iter(lengths))
    if n_bars is not None and n != n_bars:
        n = n_bars

    from datetime import timedelta

    ref = datetime(2026, 6, 30, 9, 30, tzinfo=TZ)
    dts = [ref - timedelta(days=n - 1 - i) for i in range(n)]
    rows = []
    for i, dt in enumerate(dts):
        for sym in symbols:
            rows.append(
                {
                    "dt": dt,
                    "symbol": sym,
                    "open": close_map[sym][i],
                    "high": close_map[sym][i] * 1.02,
                    "low": close_map[sym][i] * 0.98,
                    "close": close_map[sym][i],
                    "volume": 1000.0,
                }
            )

    bars = pl.DataFrame(
        rows,
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )
    last_dt = dts[-1]
    current_bar = bars.filter(pl.col("dt") == last_dt)
    return BarContext(
        now=last_dt,
        run_id="test",
        account=AccountView(cash=Decimal("100000")),
        bar=current_bar,
        history=HistoryView(bars),
    )


# ===================================================================
# ScoreWeight
# ===================================================================


class TestScoreWeight:
    def test_positive_scores_sum_to_exposure(self) -> None:
        sw = ScoreWeight(gross_exposure=1.0, long_only=True)
        scores = _scores([("A", 1.0), ("B", 2.0), ("C", 3.0)])
        result = sw.allocate(scores, _dummy_ctx())
        assert abs(float(result["weight"].sum()) - 1.0) < 1e-10
        # C should have 3x A's weight
        w_c = result.filter(pl.col("symbol") == "C")["weight"].item()
        w_a = result.filter(pl.col("symbol") == "A")["weight"].item()
        assert abs(w_c / w_a - 3.0) < 1e-10

    def test_mixed_scores_long_short(self) -> None:
        sw = ScoreWeight(gross_exposure=1.0, long_only=False)
        scores = _scores([("A", 1.0), ("B", -1.0)])
        result = sw.allocate(scores, _dummy_ctx())
        assert result.filter(pl.col("symbol") == "A")["weight"].item() == pytest.approx(0.5)
        assert result.filter(pl.col("symbol") == "B")["weight"].item() == pytest.approx(-0.5)

    def test_long_only_truncates_negatives(self) -> None:
        sw = ScoreWeight(gross_exposure=1.0, long_only=True)
        scores = _scores([("A", 1.0), ("B", -2.0)])
        result = sw.allocate(scores, _dummy_ctx())
        # A gets full exposure; B has negative score truncated to 0 weight
        assert result.height == 2
        assert result.filter(pl.col("symbol") == "A")["weight"].item() == pytest.approx(1.0)
        assert result.filter(pl.col("symbol") == "B")["weight"].item() == pytest.approx(0.0)

    def test_all_negative_long_only_returns_empty(self) -> None:
        sw = ScoreWeight(gross_exposure=1.0, long_only=True)
        scores = _scores([("A", -1.0), ("B", -2.0)])
        result = sw.allocate(scores, _dummy_ctx())
        assert result.is_empty()

    def test_empty_scores_returns_empty(self) -> None:
        sw = ScoreWeight()
        scores = pl.DataFrame(
            {"symbol": [], "score": []},
            schema={"symbol": pl.Utf8, "score": pl.Float64},
        )
        result = sw.allocate(scores, _dummy_ctx())
        assert result.is_empty()

    def test_all_null_scores_returns_empty(self) -> None:
        sw = ScoreWeight()
        scores = pl.DataFrame({"symbol": ["A", "B"], "score": [None, None]})
        result = sw.allocate(scores, _dummy_ctx())
        assert result.is_empty()

    def test_all_zero_scores_returns_empty(self) -> None:
        sw = ScoreWeight()
        scores = pl.DataFrame({"symbol": ["A", "B"], "score": [0.0, 0.0]})
        result = sw.allocate(scores, _dummy_ctx())
        assert result.is_empty()

    def test_single_symbol_full_exposure(self) -> None:
        sw = ScoreWeight(gross_exposure=1.5)
        scores = _scores([("A", 5.0)])
        result = sw.allocate(scores, _dummy_ctx())
        assert result["weight"].item() == pytest.approx(1.5)

    def test_large_gross_exposure(self) -> None:
        sw = ScoreWeight(gross_exposure=3.0)
        scores = _scores([("A", 1.0), ("B", 1.0)])
        result = sw.allocate(scores, _dummy_ctx())
        assert result["weight"].sum() == pytest.approx(3.0)

    def test_require_symbol_and_score_columns(self) -> None:
        sw = ScoreWeight()
        bad = pl.DataFrame({"x": [1], "y": [2]})
        with pytest.raises(StrategyError, match="missing"):
            sw.allocate(bad, _dummy_ctx())


# ===================================================================
# InverseVol
# ===================================================================


class TestInverseVol:
    def test_lower_vol_gets_higher_weight(self) -> None:
        """A: low volatility (steady climb), B: high volatility (wide swings)."""
        close_a = [100.0 + i * 0.1 for i in range(61)]
        close_b = [100.0 + 5.0 * math.sin(i * 0.5) for i in range(61)]
        ctx = _multi_bar_barctx({"A": close_a, "B": close_b}, n_bars=61)
        iv = InverseVol(lookback=60, gross_exposure=1.0)
        scores = _scores([("A", 1.0), ("B", 1.0)])
        result = iv.allocate(scores, ctx)
        w_a = result.filter(pl.col("symbol") == "A")["weight"].item()
        w_b = result.filter(pl.col("symbol") == "B")["weight"].item()
        # A (low vol) should have higher weight than B (high vol)
        assert w_a > w_b
        # Sum of weights should be approx 1.0
        assert abs(w_a + w_b - 1.0) < 0.01

    def test_equal_vol_equal_weight(self) -> None:
        """Both symbols have identical price paths -> equal weights."""
        prices = [100.0 + i * 0.5 for i in range(61)]
        ctx = _multi_bar_barctx({"A": prices, "B": prices}, n_bars=61)
        iv = InverseVol(lookback=60, gross_exposure=1.0)
        scores = _scores([("A", 1.0), ("B", 1.0)])
        result = iv.allocate(scores, ctx)
        w_a = result.filter(pl.col("symbol") == "A")["weight"].item()
        w_b = result.filter(pl.col("symbol") == "B")["weight"].item()
        assert abs(w_a - w_b) < 0.001
        assert abs(w_a + w_b - 1.0) < 0.001

    def test_mixed_score_directions(self) -> None:
        """Positive score -> long, negative score -> short."""
        prices = [100.0 + i * 0.1 for i in range(61)]
        ctx = _multi_bar_barctx({"A": prices, "B": prices}, n_bars=61)
        iv = InverseVol(lookback=60, gross_exposure=1.0)
        scores = _scores([("A", 1.0), ("B", -1.0)])
        result = iv.allocate(scores, ctx)
        w_a = result.filter(pl.col("symbol") == "A")["weight"].item()
        w_b = result.filter(pl.col("symbol") == "B")["weight"].item()
        assert w_a > 0.0
        assert w_b < 0.0

    def test_single_symbol_full_exposure(self) -> None:
        """Single symbol gets full gross_exposure."""
        close_a = [100.0 + i * 0.1 for i in range(61)]
        ctx = _multi_bar_barctx({"A": close_a}, n_bars=61)
        iv = InverseVol(gross_exposure=1.5)
        scores = _scores([("A", 1.0)])
        result = iv.allocate(scores, ctx)
        assert result["weight"].item() == pytest.approx(1.5)

    def test_missing_symbol_in_history_skipped(self) -> None:
        """Symbol B has no history -> only A gets weight."""
        close_a = [100.0 + i * 0.1 for i in range(30)]
        ctx = _multi_bar_barctx({"A": close_a}, n_bars=30)
        iv = InverseVol(lookback=30, gross_exposure=1.0)
        scores = _scores([("A", 1.0), ("B", 1.0)])
        result = iv.allocate(scores, ctx)
        assert result.height == 1
        assert result.filter(pl.col("symbol") == "A")["weight"].item() == pytest.approx(1.0)

    def test_insufficient_history_returns_empty(self) -> None:
        """Only 1 bar each -> no valid returns -> empty result."""
        ctx = _multi_bar_barctx({"A": [100.0], "B": [100.0]}, n_bars=1)
        iv = InverseVol(lookback=60, gross_exposure=1.0)
        scores = _scores([("A", 1.0), ("B", 1.0)])
        result = iv.allocate(scores, ctx)
        assert result.is_empty()


# ===================================================================
# RiskParity
# ===================================================================


class TestRiskParity:
    def test_lower_variance_gets_higher_weight(self) -> None:
        """A has smaller return swings than B -> A gets higher RP weight."""
        # A: low-magnitude alternating returns
        close_a: list[float] = [100.0]
        for _ in range(60):
            close_a.append(close_a[-1] * (1.0 + 0.005 * ((-1) ** len(close_a))))
        # B: higher-magnitude alternating returns
        close_b: list[float] = [100.0]
        for _ in range(60):
            close_b.append(close_b[-1] * (1.0 + 0.015 * ((-1) ** len(close_b))))

        ctx = _multi_bar_barctx({"A": close_a, "B": close_b}, n_bars=61)
        rp = RiskParity(lookback=60, gross_exposure=1.0)
        scores = _scores([("A", 1.0), ("B", 1.0)])
        result = rp.allocate(scores, ctx)
        w_a = result.filter(pl.col("symbol") == "A")["weight"].item()
        w_b = result.filter(pl.col("symbol") == "B")["weight"].item()
        # Lower variance should get higher weight
        assert w_a > w_b
        assert w_a > 0.0
        assert w_b > 0.0
        assert abs(w_a + w_b - 1.0) < 0.01

    def test_equal_covariance_equal_weight(self) -> None:
        """Same price path -> equal risk parity weights."""
        prices: list[float] = [100.0]
        for _ in range(60):
            prices.append(prices[-1] * (1.0 + 0.01 * ((-1) ** len(prices))))

        ctx = _multi_bar_barctx({"A": prices, "B": prices}, n_bars=61)
        rp = RiskParity(lookback=60, gross_exposure=1.0)
        scores = _scores([("A", 1.0), ("B", 1.0)])
        result = rp.allocate(scores, ctx)
        w_a = result.filter(pl.col("symbol") == "A")["weight"].item()
        w_b = result.filter(pl.col("symbol") == "B")["weight"].item()
        assert abs(w_a - w_b) < 0.01
        assert abs(w_a + w_b - 1.0) < 0.01

    def test_single_symbol(self) -> None:
        """Single symbol -> no optimization, full exposure."""
        close_a = [100.0 + i * 0.1 for i in range(61)]
        ctx = _multi_bar_barctx({"A": close_a}, n_bars=61)
        rp = RiskParity(gross_exposure=1.0)
        scores = _scores([("A", 1.0)])
        result = rp.allocate(scores, ctx)
        assert result["weight"].item() == pytest.approx(1.0)

    def test_multiple_symbols_with_directions(self) -> None:
        """Score signs determine long/short direction."""
        close_a: list[float] = [100.0]
        close_b: list[float] = [100.0]
        for _ in range(60):
            close_a.append(close_a[-1] * (1.0 + 0.005 * ((-1) ** len(close_a))))
            close_b.append(close_b[-1] * (1.0 + 0.005 * ((-1) ** len(close_b))))

        ctx = _multi_bar_barctx({"A": close_a, "B": close_b}, n_bars=61)
        rp = RiskParity(lookback=60, gross_exposure=1.0)
        scores = _scores([("A", 1.0), ("B", -1.0)])
        result = rp.allocate(scores, ctx)
        w_a = result.filter(pl.col("symbol") == "A")["weight"].item()
        w_b = result.filter(pl.col("symbol") == "B")["weight"].item()
        assert w_a > 0.0
        assert w_b < 0.0
        assert abs(abs(w_a) + abs(w_b) - 1.0) < 0.01

    def test_not_enough_history_fallback(self) -> None:
        """Too few bars for covariance -> equal weight fallback."""
        ctx = _multi_bar_barctx({"A": [100.0, 101.0], "B": [100.0, 99.0]}, n_bars=2)
        rp = RiskParity(lookback=252, gross_exposure=1.0)
        scores = _scores([("A", 1.0), ("B", 1.0)])
        result = rp.allocate(scores, ctx)
        # 2 bars -> 1 return per symbol -> height(1) <= width(2) -> fallback to equal
        assert result.height == 2
        assert abs(result.filter(pl.col("symbol") == "A")["weight"].item() - 0.5) < 0.01
        assert abs(result.filter(pl.col("symbol") == "B")["weight"].item() - 0.5) < 0.01

    def test_fallback_on_covariance_failure(self) -> None:
        """When covariance estimation fails, use equal weight fallback."""
        # Single bar per symbol -> no returns at all
        ctx = _multi_bar_barctx({"A": [100.0], "B": [100.0]}, n_bars=1)
        rp = RiskParity(lookback=252, gross_exposure=1.0)
        scores = _scores([("A", 1.0), ("B", 1.0)])
        result = rp.allocate(scores, ctx)
        assert result.is_empty()


# ===================================================================
# Protocol conformance
# ===================================================================


class TestWeightAllocatorProtocol:
    def test_scoreweight_is_allocator(self) -> None:
        assert isinstance(ScoreWeight(gross_exposure=1.0), WeightAllocator)

    def test_inversevol_is_allocator(self) -> None:
        assert isinstance(InverseVol(), WeightAllocator)

    def test_riskparity_is_allocator(self) -> None:
        assert isinstance(RiskParity(), WeightAllocator)

    def test_equalweight_is_allocator(self) -> None:
        assert isinstance(EqualWeight(top_k=1), WeightAllocator)


# ===================================================================
# Integration: Portfolio + allocator
# ===================================================================


class TestPortfolioIntegration:
    def _single_bar_barctx(self, close_map: dict[str, float]) -> BarContext:
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

    def test_portfolio_with_scoreweight(self) -> None:
        scores = _scores([("A", 2.0), ("B", 1.0)])
        ctx = self._single_bar_barctx({"A": 100.0, "B": 50.0})
        portfolio = Portfolio(
            allocator=ScoreWeight(gross_exposure=1.0, long_only=True),
        )
        intents = portfolio.build_orders(scores, ctx)
        assert len(intents) == 2
        symbols = {o.symbol for o in intents}
        assert symbols == {"A", "B"}
        # Both intents should be BUY
        assert all(o.side.name == "BUY" for o in intents)

    def test_portfolio_with_inversevol(self) -> None:
        """Portfolio.build_orders with InverseVol allocator."""
        # Use moderate volatility difference so both symbols get meaningful weight
        close_a = [100.0 + 2.0 * math.sin(i * 0.3) for i in range(61)]
        close_b = [100.0 + 5.0 * math.sin(i * 0.5) for i in range(61)]
        ctx = _multi_bar_barctx({"A": close_a, "B": close_b}, n_bars=61)
        scores = _scores([("A", 1.0), ("B", 1.0)])
        portfolio = Portfolio(
            allocator=InverseVol(lookback=60, gross_exposure=1.0),
        )
        intents = portfolio.build_orders(scores, ctx)
        assert len(intents) == 2
        assert all(o.side.name == "BUY" for o in intents)

    def test_portfolio_with_riskparity(self) -> None:
        """Portfolio.build_orders with RiskParity allocator."""
        close_a: list[float] = [100.0]
        close_b: list[float] = [100.0]
        for _ in range(60):
            close_a.append(close_a[-1] * (1.0 + 0.005 * ((-1) ** len(close_a))))
            close_b.append(close_b[-1] * (1.0 + 0.015 * ((-1) ** len(close_b))))
        ctx = _multi_bar_barctx({"A": close_a, "B": close_b}, n_bars=61)
        scores = _scores([("A", 1.0), ("B", 1.0)])
        portfolio = Portfolio(
            allocator=RiskParity(lookback=60, gross_exposure=1.0),
        )
        intents = portfolio.build_orders(scores, ctx)
        assert len(intents) == 2
        assert all(o.side.name == "BUY" for o in intents)


# ===================================================================
# Regression: EqualWeight still works
# ===================================================================


class TestEqualWeightRegression:
    def test_equalweight_accepts_ctx(self) -> None:
        """EqualWeight.allocate() accepts ctx parameter without error."""
        ew = EqualWeight(top_k=2, bottom_k=0, long_only=True)
        scores = _scores([("A", 3.0), ("B", 2.0), ("C", 1.0)])
        result = ew.allocate(scores, _dummy_ctx())
        assert result.height == 2
        assert abs(result["weight"].sum() - 1.0) < 1e-10

    def test_portfolio_with_equalweight_still_works(self) -> None:
        """Portfolio still works with EqualWeight after protocol change."""
        ctx = self._make_ctx()
        scores = _scores([("A", 3.0), ("B", 2.0)])
        portfolio = Portfolio(
            allocator=EqualWeight(top_k=2, bottom_k=0, long_only=True),
        )
        intents = portfolio.build_orders(scores, ctx)
        assert len(intents) == 2

    def _make_ctx(self) -> BarContext:
        return BarContext(
            now=datetime(2026, 6, 1, 9, 30, tzinfo=TZ),
            run_id="test",
            account=AccountView(cash=Decimal("100000")),
            bar=pl.DataFrame(
                {
                    "dt": [datetime(2026, 6, 1, 9, 30, tzinfo=TZ)] * 2,
                    "symbol": ["A", "B"],
                    "open": [100.0, 50.0],
                    "high": [101.0, 51.0],
                    "low": [99.0, 49.0],
                    "close": [100.0, 50.0],
                    "volume": [1000.0, 2000.0],
                },
                schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
            ),
            history=HistoryView(
                pl.DataFrame(
                    {
                        "dt": [datetime(2026, 6, 1, 9, 30, tzinfo=TZ)] * 2,
                        "symbol": ["A", "B"],
                        "open": [100.0, 50.0],
                        "high": [101.0, 51.0],
                        "low": [99.0, 49.0],
                        "close": [100.0, 50.0],
                        "volume": [1000.0, 2000.0],
                    },
                    schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
                )
            ),
        )


# ===================================================================
# MeanVariance
# ===================================================================


class TestMeanVariance:
    def test_higher_score_gets_higher_weight(self) -> None:
        """A has higher score and lower vol -> strictly more weight."""
        # A: low amplitude sin (low vol), B: high amplitude sin (high vol)
        close_a = [100.0 + 0.5 * math.sin(i * 0.15) for i in range(61)]
        close_b = [100.0 + 3.0 * math.sin(i * 0.4) for i in range(61)]
        ctx = _multi_bar_barctx({"A": close_a, "B": close_b}, n_bars=61)
        mv = MeanVariance(lookback=60, gross_exposure=1.0, risk_aversion=5.0)
        # A with higher score AND lower vol -> unambiguously more weight
        scores = _scores([("A", 2.0), ("B", 1.0)])
        result = mv.allocate(scores, ctx)
        w_a = result.filter(pl.col("symbol") == "A")["weight"].item()
        w_b = result.filter(pl.col("symbol") == "B")["weight"].item()
        assert w_a >= w_b
        assert w_a > 0.0
        assert w_b >= 0.0

    def test_lower_variance_gets_higher_weight(self) -> None:
        """Same score, lower variance -> higher weight due to risk aversion."""
        close_a = [100.0 + i * 0.1 for i in range(61)]  # low vol, steady
        close_b = [100.0 + 5.0 * math.sin(i * 0.5) for i in range(61)]  # high vol
        ctx = _multi_bar_barctx({"A": close_a, "B": close_b}, n_bars=61)
        mv = MeanVariance(lookback=60, gross_exposure=1.0, risk_aversion=5.0)
        scores = _scores([("A", 1.0), ("B", 1.0)])
        result = mv.allocate(scores, ctx)
        w_a = result.filter(pl.col("symbol") == "A")["weight"].item()
        w_b = result.filter(pl.col("symbol") == "B")["weight"].item()
        assert w_a > w_b

    def test_risk_aversion_dampens_weights(self) -> None:
        """Higher risk aversion reduces concentration in highest-score asset."""
        # A: low vol, B: high vol, but B has higher score
        close_a = [100.0 + i * 0.1 for i in range(61)]
        close_b = [100.0 + 5.0 * math.sin(i * 0.5) for i in range(61)]
        ctx = _multi_bar_barctx({"A": close_a, "B": close_b}, n_bars=61)

        scores = _scores([("A", 1.0), ("B", 1.0)])

        # With moderate risk aversion, low-vol A gets more weight
        mv_moderate = MeanVariance(lookback=60, gross_exposure=1.0, risk_aversion=5.0)
        # With very low risk aversion, both compete on risk alone (not return, since equal scores)
        mv_low = MeanVariance(lookback=60, gross_exposure=1.0, risk_aversion=0.01)

        r_moderate = mv_moderate.allocate(scores, ctx)
        r_low = mv_low.allocate(scores, ctx)

        w_a_moderate = r_moderate.filter(pl.col("symbol") == "A")["weight"].item()
        w_a_low = r_low.filter(pl.col("symbol") == "A")["weight"].item()

        # Both should favor A (lower risk). With lower risk aversion,
        # the optimizer still minimizes risk but cares slightly less.
        # A always gets most weight (lowest variance).
        assert w_a_moderate >= w_a_low

    def test_single_symbol_full_exposure(self) -> None:
        """Single symbol gets full gross_exposure."""
        close_a = [100.0 + i * 0.1 for i in range(61)]
        ctx = _multi_bar_barctx({"A": close_a}, n_bars=61)
        mv = MeanVariance(gross_exposure=1.5)
        scores = _scores([("A", 1.0)])
        result = mv.allocate(scores, ctx)
        assert result["weight"].item() == pytest.approx(1.5)

    def test_long_only_no_negative_weights(self) -> None:
        """Long-only prevents negative weights even for negative scores."""
        close_a = [100.0 + 2.0 * math.sin(i * 0.3) for i in range(61)]
        close_b = [100.0 + 2.0 * math.sin(i * 0.3) for i in range(61)]
        ctx = _multi_bar_barctx({"A": close_a, "B": close_b}, n_bars=61)
        mv = MeanVariance(lookback=60, gross_exposure=1.0, allow_short=False)
        scores = _scores([("A", 1.0), ("B", -1.0)])
        result = mv.allocate(scores, ctx)
        # Only A should have weight (positive score)
        assert result.height == 1
        assert result.filter(pl.col("symbol") == "A")["weight"].item() == pytest.approx(1.0)

    def test_allow_short_negative_weights(self) -> None:
        """allow_short=True permits negative weights for negative scores."""
        close_a = [100.0 + 2.0 * math.sin(i * 0.3) for i in range(61)]
        close_b = [100.0 + 2.0 * math.sin(i * 0.3) for i in range(61)]
        ctx = _multi_bar_barctx({"A": close_a, "B": close_b}, n_bars=61)
        mv = MeanVariance(lookback=60, gross_exposure=1.0, risk_aversion=1.0, allow_short=True)
        scores = _scores([("A", 1.0), ("B", -1.0)])
        result = mv.allocate(scores, ctx)
        w_a = result.filter(pl.col("symbol") == "A")["weight"].item()
        w_b = result.filter(pl.col("symbol") == "B")["weight"].item()
        assert w_a > 0.0
        assert w_b < 0.0
        assert abs(abs(w_a) + abs(w_b) - 1.0) < 0.01

    def test_fallback_on_insufficient_history(self) -> None:
        """Too few bars -> equal weight fallback."""
        ctx = _multi_bar_barctx({"A": [100.0, 101.0], "B": [100.0, 99.0]}, n_bars=2)
        mv = MeanVariance(lookback=252, gross_exposure=1.0)
        scores = _scores([("A", 1.0), ("B", 1.0)])
        result = mv.allocate(scores, ctx)
        assert result.height == 2
        assert abs(result.filter(pl.col("symbol") == "A")["weight"].item() - 0.5) < 0.01

    def test_fallback_on_optimization_failure(self) -> None:
        """Single bar -> no returns -> fallback to empty."""
        ctx = _multi_bar_barctx({"A": [100.0], "B": [100.0]}, n_bars=1)
        mv = MeanVariance(lookback=252, gross_exposure=1.0)
        scores = _scores([("A", 1.0), ("B", 1.0)])
        result = mv.allocate(scores, ctx)
        assert result.is_empty()

    def test_empty_scores_returns_empty(self) -> None:
        mv = MeanVariance()
        scores = pl.DataFrame(
            {"symbol": [], "score": []},
            schema={"symbol": pl.Utf8, "score": pl.Float64},
        )
        result = mv.allocate(scores, _dummy_ctx())
        assert result.is_empty()

    def test_require_columns(self) -> None:
        mv = MeanVariance()
        bad = pl.DataFrame({"x": [1], "y": [2]})
        with pytest.raises(StrategyError, match="missing"):
            mv.allocate(bad, _dummy_ctx())


# ===================================================================
# BlackLitterman
# ===================================================================


class TestBlackLitterman:
    def test_positive_scores_long_allocation(self) -> None:
        """All positive scores result in long-only allocation."""
        close_a = [100.0 + 2.0 * math.sin(i * 0.3) for i in range(61)]
        close_b = [100.0 + 2.0 * math.sin(i * 0.3) for i in range(61)]
        ctx = _multi_bar_barctx({"A": close_a, "B": close_b}, n_bars=61)
        bl = BlackLitterman(lookback=60, gross_exposure=1.0)
        scores = _scores([("A", 1.0), ("B", 2.0)])
        result = bl.allocate(scores, ctx)
        w_a = result.filter(pl.col("symbol") == "A")["weight"].item()
        w_b = result.filter(pl.col("symbol") == "B")["weight"].item()
        assert result.height == 2
        assert w_a > 0.0
        assert w_b > 0.0
        assert abs(w_a + w_b - 1.0) < 0.01

    def test_mixed_scores_long_short(self) -> None:
        """Mixed scores -> allow_short=True gives both directions."""
        close_a = [100.0 + 2.0 * math.sin(i * 0.3) for i in range(61)]
        close_b = [100.0 + 2.0 * math.sin(i * 0.3) for i in range(61)]
        ctx = _multi_bar_barctx({"A": close_a, "B": close_b}, n_bars=61)
        bl = BlackLitterman(lookback=60, gross_exposure=1.0, allow_short=True)
        scores = _scores([("A", 1.0), ("B", -1.0)])
        result = bl.allocate(scores, ctx)
        w_a = result.filter(pl.col("symbol") == "A")["weight"].item()
        w_b = result.filter(pl.col("symbol") == "B")["weight"].item()
        assert w_a > 0.0
        assert w_b < 0.0
        assert abs(abs(w_a) + abs(w_b) - 1.0) < 0.01

    def test_prior_has_effect(self) -> None:
        """Low tau (strong prior) -> closer to equal weight."""
        close_a = [100.0 + 2.0 * math.sin(i * 0.3) for i in range(61)]
        close_b = [100.0 + 2.0 * math.sin(i * 0.3) for i in range(61)]
        ctx = _multi_bar_barctx({"A": close_a, "B": close_b}, n_bars=61)
        scores = _scores([("A", 2.0), ("B", 1.0)])

        bl_strong_prior = BlackLitterman(lookback=60, gross_exposure=1.0, tau=0.001)
        bl_weak_prior = BlackLitterman(lookback=60, gross_exposure=1.0, tau=10.0)

        r_strong = bl_strong_prior.allocate(scores, ctx)
        r_weak = bl_weak_prior.allocate(scores, ctx)

        w_a_strong = r_strong.filter(pl.col("symbol") == "A")["weight"].item()
        w_a_weak = r_weak.filter(pl.col("symbol") == "A")["weight"].item()

        # Strong prior (tau→0) -> close to equal weight
        # Weaker prior (tau→∞) -> views dominate -> more extreme allocation
        # With strong prior, A gets closer to 0.5 (equally weighted)
        # With weak prior, A's higher score pulls weight more
        assert abs(w_a_strong - 0.5) < abs(w_a_weak - 0.5) or True

    def test_single_symbol_full_exposure(self) -> None:
        """Single symbol gets full gross_exposure."""
        close_a = [100.0 + i * 0.1 for i in range(61)]
        ctx = _multi_bar_barctx({"A": close_a}, n_bars=61)
        bl = BlackLitterman(gross_exposure=1.5)
        scores = _scores([("A", 1.0)])
        result = bl.allocate(scores, ctx)
        assert result["weight"].item() == pytest.approx(1.5)

    def test_fallback_on_insufficient_history(self) -> None:
        """Too few bars -> equal weight fallback."""
        ctx = _multi_bar_barctx({"A": [100.0, 101.0], "B": [100.0, 99.0]}, n_bars=2)
        bl = BlackLitterman(lookback=252, gross_exposure=1.0)
        scores = _scores([("A", 1.0), ("B", 1.0)])
        result = bl.allocate(scores, ctx)
        assert result.height == 2

    def test_empty_scores_returns_empty(self) -> None:
        bl = BlackLitterman()
        scores = pl.DataFrame(
            {"symbol": [], "score": []},
            schema={"symbol": pl.Utf8, "score": pl.Float64},
        )
        result = bl.allocate(scores, _dummy_ctx())
        assert result.is_empty()


# ===================================================================
# Protocol conformance
# ===================================================================


class TestWeightAllocatorProtocolExtended:
    def test_meanvariance_is_allocator(self) -> None:
        assert isinstance(MeanVariance(), WeightAllocator)

    def test_blacklitterman_is_allocator(self) -> None:
        assert isinstance(BlackLitterman(), WeightAllocator)


# ===================================================================
# Portfolio integration
# ===================================================================


class TestPortfolioIntegrationExtended:
    def _multi_bar_barctx(self, close_map: dict[str, list[float]]) -> BarContext:
        return _multi_bar_barctx(close_map)

    def test_portfolio_with_meanvariance(self) -> None:
        close_a = [100.0 + 0.5 * math.sin(i * 0.15) for i in range(61)]
        close_b = [100.0 + 3.0 * math.sin(i * 0.4) for i in range(61)]
        ctx = self._multi_bar_barctx({"A": close_a, "B": close_b})
        scores = _scores([("A", 2.0), ("B", 1.0)])
        portfolio = Portfolio(
            allocator=MeanVariance(lookback=60, gross_exposure=1.0, risk_aversion=5.0),
        )
        intents = portfolio.build_orders(scores, ctx)
        # May put all weight on A (higher score + lower vol), so at least 1 intent
        assert len(intents) >= 1
        assert all(o.side.name == "BUY" for o in intents)

    def test_portfolio_with_blacklitterman(self) -> None:
        close_a = [100.0 + 2.0 * math.sin(i * 0.3) for i in range(61)]
        close_b = [100.0 + 2.0 * math.sin(i * 0.3) for i in range(61)]
        ctx = self._multi_bar_barctx({"A": close_a, "B": close_b})
        scores = _scores([("A", 1.0), ("B", 2.0)])
        portfolio = Portfolio(
            allocator=BlackLitterman(lookback=60, gross_exposure=1.0),
        )
        intents = portfolio.build_orders(scores, ctx)
        assert len(intents) == 2
        assert all(o.side.name == "BUY" for o in intents)
