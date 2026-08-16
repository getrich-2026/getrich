"""Tests for the SignalProducer."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import polars as pl
import pytest
from gr_backtest import (
    AccountView,
    BarContext,
    HistoryView,
    OrderIntent,
    Strategy,
    get_shanghai_tz,
)
from gr_backtest.strategy.signal import SignalStrategy
from gr_backtest.types import Side
from gr_signal.live import SignalProducer, SignalProductionError


if TYPE_CHECKING:
    from collections.abc import Iterable


TZ = get_shanghai_tz()


def _bar_ctx(
    symbols: list[str],
    close_map: dict[str, float],
    now: datetime | None = None,
) -> BarContext:
    """Build a single-bar BarContext for testing."""
    if now is None:
        now = datetime(2026, 6, 1, 9, 30, tzinfo=TZ)
    bar = pl.DataFrame(
        {
            "dt": [now] * len(symbols),
            "symbol": symbols,
            "open": [close_map[s] * 0.99 for s in symbols],
            "high": [close_map[s] * 1.01 for s in symbols],
            "low": [close_map[s] * 0.98 for s in symbols],
            "close": [close_map[s] for s in symbols],
            "volume": [1000.0] * len(symbols),
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )
    return BarContext(
        now=now,
        run_id="test",
        account=AccountView(cash=Decimal("100000")),
        bar=bar,
        history=HistoryView(bar),
    )


# ---------------------------------------------------------------------------
# Test strategies
# ---------------------------------------------------------------------------


class _TestSignalStrategy(SignalStrategy):
    """Signal strategy with configurable scores."""

    def __init__(self, scores: list[tuple[str, float]]) -> None:
        super().__init__()
        self._scores = scores

    @property
    def name(self) -> str:
        return "TestSignalStrategy"

    def compute_signal(self, ctx: BarContext) -> pl.DataFrame:
        return pl.DataFrame(
            {"symbol": [s for s, _ in self._scores], "score": [sc for _, sc in self._scores]}
        )


class _TestPlainStrategy(Strategy):
    """Plain strategy with configurable intents."""

    def __init__(self, intents: list[OrderIntent]) -> None:
        super().__init__()
        self._intents = intents
        self.on_bar_call_count = 0

    @property
    def name(self) -> str:
        return "TestPlainStrategy"

    def on_bar(self, ctx: BarContext) -> Iterable[OrderIntent] | None:
        self.on_bar_call_count += 1
        return self._intents if self._intents else None


class _NoSignalStrategy(Strategy):
    @property
    def name(self) -> str:
        return "NoSignalStrategy"

    def on_bar(self, ctx: BarContext) -> Iterable[OrderIntent] | None:
        return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSignalProducer:
    def test_produce_from_signal_strategy(self) -> None:
        """SignalStrategy scores produce a signal DataFrame."""
        strategy = _TestSignalStrategy([("A", 2.0), ("B", 1.0)])
        producer = SignalProducer(strategy)
        ctx = _bar_ctx(["A", "B"], {"A": 100.0, "B": 50.0})
        result = producer.produce(ctx)

        assert not result.is_empty()
        assert result.height == 2
        assert set(result["symbol"].to_list()) == {"A", "B"}
        assert result["action"].to_list() == ["buy", "buy"]
        assert result["direction"].to_list() == ["long", "long"]
        # A has higher score -> higher confidence
        conf = dict(zip(result["symbol"].to_list(), result["confidence"].to_list(), strict=True))
        assert conf["A"] > conf["B"]
        # trigger_price from bar close
        assert result.filter(pl.col("symbol") == "A")["trigger_price"].item() == 100.0
        assert result.filter(pl.col("symbol") == "B")["trigger_price"].item() == 50.0

    def test_produce_mixed_scores(self) -> None:
        """Positive and negative scores produce buy/sell signals."""
        strategy = _TestSignalStrategy([("A", 2.0), ("B", -1.0)])
        producer = SignalProducer(strategy)
        ctx = _bar_ctx(["A", "B"], {"A": 100.0, "B": 50.0})
        result = producer.produce(ctx)

        assert result.height == 2
        actions = dict(zip(result["symbol"].to_list(), result["action"].to_list(), strict=True))
        assert actions["A"] == "buy"
        assert actions["B"] == "sell"
        directions = dict(
            zip(result["symbol"].to_list(), result["direction"].to_list(), strict=True)
        )
        assert directions["A"] == "long"
        assert directions["B"] == "short"

    def test_confidence_from_score(self) -> None:
        """Confidence is normalized to [0, 1] based on max abs score."""
        strategy = _TestSignalStrategy([("A", 3.0), ("B", 1.0), ("C", -2.0)])
        producer = SignalProducer(strategy)
        ctx = _bar_ctx(["A", "B", "C"], {"A": 100.0, "B": 50.0, "C": 30.0})
        result = producer.produce(ctx)

        conf = dict(zip(result["symbol"].to_list(), result["confidence"].to_list(), strict=True))
        # max abs score is 3 -> A: 3/3=1.0, B: 1/3≈0.333, C: 2/3≈0.667
        assert conf["A"] == pytest.approx(1.0)
        assert conf["B"] == pytest.approx(1.0 / 3)
        assert conf["C"] == pytest.approx(2.0 / 3)

    def test_produce_no_signal_signal_strategy(self) -> None:
        """When SignalStrategy returns no scores, empty DataFrame returned."""
        strategy = _TestSignalStrategy([])
        producer = SignalProducer(strategy)
        ctx = _bar_ctx(["A"], {"A": 100.0})
        result = producer.produce(ctx)
        assert result.is_empty()

    def test_produce_no_signal_plain_strategy(self) -> None:
        """When plain Strategy returns None, empty DataFrame returned."""
        strategy = _NoSignalStrategy()
        producer = SignalProducer(strategy)
        ctx = _bar_ctx(["A"], {"A": 100.0})
        result = producer.produce(ctx)
        assert result.is_empty()

    def test_produce_from_plain_strategy(self) -> None:
        """Plain Strategy on_bar produces signal DataFrame."""
        intents = [
            OrderIntent(symbol="A", side=Side.BUY, qty=Decimal("100")),
            OrderIntent(symbol="B", side=Side.SELL, qty=Decimal("50")),
        ]
        strategy = _TestPlainStrategy(intents)
        producer = SignalProducer(strategy)
        ctx = _bar_ctx(["A", "B"], {"A": 100.0, "B": 50.0})
        result = producer.produce(ctx)

        assert not result.is_empty()
        assert result.height == 2
        actions = dict(zip(result["symbol"].to_list(), result["action"].to_list(), strict=True))
        assert actions["A"] == "buy"
        assert actions["B"] == "sell"
        # Plain strategy has no confidence
        assert all(r is None for r in result["confidence"].to_list())

    def test_last_signal_df_cached(self) -> None:
        """After produce(), last_signal_df is set."""
        strategy = _TestSignalStrategy([("A", 1.0)])
        producer = SignalProducer(strategy)
        ctx = _bar_ctx(["A"], {"A": 100.0})
        assert producer.last_signal_df is None
        producer.produce(ctx)
        assert producer.last_signal_df is not None
        assert not producer.last_signal_df.is_empty()

    def test_to_signals_conversion(self) -> None:
        """to_signals converts DataFrame to Signal objects."""
        strategy = _TestSignalStrategy([("A", 2.0), ("B", -1.0)])
        producer = SignalProducer(strategy)
        ctx = _bar_ctx(["A", "B"], {"A": 100.0, "B": 50.0})
        df = producer.produce(ctx)
        signals = producer.to_signals(df)

        assert len(signals) == 2
        sig_a = next(s for s in signals if s.symbol == "A")
        sig_b = next(s for s in signals if s.symbol == "B")

        assert sig_a.action == "buy"
        assert sig_b.action == "sell"
        assert sig_a.direction == "long"
        assert sig_b.direction == "short"
        assert sig_a.trigger_price == Decimal("100")
        assert sig_b.trigger_price == Decimal("50")
        assert sig_a.confidence is not None
        assert sig_b.confidence is not None

    def test_to_signals_empty(self) -> None:
        """to_signals returns empty list for empty DataFrame."""
        producer = SignalProducer(_NoSignalStrategy())
        signals = producer.to_signals(pl.DataFrame())
        assert signals == []

    def test_produce_empty_scores(self) -> None:
        """All-null scores produce empty signal DataFrame."""
        strategy = _TestSignalStrategy([("A", None), ("B", None)])  # type: ignore[list-item]
        producer = SignalProducer(strategy)
        ctx = _bar_ctx(["A", "B"], {"A": 100.0, "B": 50.0})
        result = producer.produce(ctx)
        assert result.is_empty()

    def test_get_bar_close_extracts_prices(self) -> None:
        """_get_bar_close extracts {symbol: close} mapping."""
        ctx = _bar_ctx(["A", "B"], {"A": 100.0, "B": 50.0})
        result = SignalProducer._get_bar_close(ctx)
        assert result == {"A": 100.0, "B": 50.0}

    def test_trigger_price_null_when_symbol_not_in_bar(self) -> None:
        """Symbol in scores but not in bar: trigger_price defaults to None."""
        strategy = _TestSignalStrategy([("A", 1.0), ("B", -1.0)])
        producer = SignalProducer(strategy)
        # Only provide bar data for A; B is absent
        ctx = _bar_ctx(["A"], {"A": 100.0})
        result = producer.produce(ctx)

        assert not result.is_empty()
        # B should still appear in the signal (from scores) but with null trigger_price
        symbols_present = result["symbol"].to_list()
        assert "B" in symbols_present
        trigger_b = result.filter(pl.col("symbol") == "B")["trigger_price"].item()
        assert trigger_b is None

    def test_produce_from_plain_strategy_invalid_intent_raises(self) -> None:
        """Non-OrderIntent in on_bar return raises SignalProductionError."""

        class _BadStrategy(Strategy):
            @property
            def name(self) -> str:
                return "Bad"

            def on_bar(self, ctx: BarContext) -> Iterable:
                return ["not_an_order_intent"]  # type: ignore[return-value]

        producer = SignalProducer(_BadStrategy())
        ctx = _bar_ctx(["A"], {"A": 100.0})
        with pytest.raises(SignalProductionError):
            producer.produce(ctx)
