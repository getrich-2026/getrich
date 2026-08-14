"""Tests for SignalStrategy."""

from datetime import datetime
from decimal import Decimal

import polars as pl
import pytest

from getrich_backtest import (
    AccountView,
    Backtest,
    BarContext,
    DataFrameBarLoader,
    EqualWeight,
    HistoryView,
    Portfolio,
    StrategyError,
    get_shanghai_tz,
)
from getrich_backtest.strategy.signal import SignalStrategy


TZ = get_shanghai_tz()


def test_signal_strategy_requires_portfolio() -> None:
    """SignalStrategy without portfolio should raise on on_bar."""

    class BadStrat(SignalStrategy):
        portfolio = None

        def compute_signal(self, ctx):
            return pl.DataFrame({"symbol": [], "score": []})

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
    ctx = BarContext(
        now=datetime(2026, 6, 1, 9, 30, tzinfo=TZ),
        run_id="test",
        account=AccountView(cash=Decimal("10000")),
        bar=bar,
        history=HistoryView(bar),
    )
    strat = BadStrat()
    with pytest.raises(StrategyError, match="Portfolio"):
        strat.on_bar(ctx)


def test_signal_strategy_compute_signal_not_implemented() -> None:
    """Base class raises NotImplementedError."""

    strat = SignalStrategy()
    with pytest.raises(NotImplementedError, match="compute_signal"):
        strat.compute_signal(None)  # type: ignore[arg-type]


def test_signal_strategy_returns_none_on_empty_scores() -> None:
    """Empty scores should produce None (no intents)."""

    class EmptyStrat(SignalStrategy):
        portfolio = Portfolio(allocator=EqualWeight(top_k=2, long_only=True))

        def compute_signal(self, ctx):
            return pl.DataFrame({"symbol": [], "score": []})

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
    ctx = BarContext(
        now=datetime(2026, 6, 1, 9, 30, tzinfo=TZ),
        run_id="test",
        account=AccountView(cash=Decimal("10000")),
        bar=bar,
        history=HistoryView(bar),
    )
    result = EmptyStrat().on_bar(ctx)
    assert result is None


def test_signal_strategy_integration_via_backtest_run() -> None:
    """Full end-to-end: SignalStrategy through Backtest.run()."""

    class MomentumSignal(SignalStrategy):
        portfolio = Portfolio(
            allocator=EqualWeight(top_k=2, long_only=True),
        )

        def compute_signal(self, ctx):
            # Use close price as signal (higher = better)
            return pl.DataFrame({"symbol": ["A", "B", "C"], "score": [10.0, 5.0, 1.0]})

    # 5 bars of data across 3 symbols
    n = 5
    symbols_data = ["A", "B", "C"]
    prices = {"A": 10.0, "B": 20.0, "C": 30.0}
    rows = []
    for i in range(n):
        for sym in symbols_data:
            rows.append(
                {
                    "dt": datetime(2026, 6, i + 1, 9, 30, tzinfo=TZ),
                    "symbol": sym,
                    "open": prices[sym],
                    "high": prices[sym] * 1.02,
                    "low": prices[sym] * 0.98,
                    "close": prices[sym],
                    "volume": 1000.0,
                }
            )
    df = pl.DataFrame(rows, schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")})

    bt = Backtest(
        strategy=MomentumSignal(),
        bar_loader=DataFrameBarLoader(df),
        symbols=["A", "B", "C"],
        start=datetime(2026, 6, 1, tzinfo=TZ),
        end=datetime(2026, 6, 5, tzinfo=TZ),
        initial_cash=Decimal("100000"),
    )
    result = bt.run()
    # Should produce fills for A and B (top 2 by score)
    assert len(result.fills) >= 2
    filled_symbols = {f.symbol for f in result.fills}
    assert "A" in filled_symbols
    assert "B" in filled_symbols
