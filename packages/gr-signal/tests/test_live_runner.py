"""Tests for live signal runner orchestration."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from decimal import Decimal

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
from gr_backtest.types import Side
from gr_signal import LiveDataError, LiveSignalRunner
from gr_signal.live import Signal


TZ = get_shanghai_tz()


def _bar_ctx() -> BarContext:
    now = datetime(2026, 6, 1, 9, 30, tzinfo=TZ)
    bar = pl.DataFrame(
        {
            "dt": [now],
            "symbol": ["A"],
            "open": [10.0],
            "high": [10.2],
            "low": [9.9],
            "close": [10.1],
            "volume": [1000.0],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )
    return BarContext(
        now=now,
        run_id="live-test",
        account=AccountView(cash=Decimal("0"), available_cash=Decimal("0")),
        bar=bar,
        history=HistoryView(bar),
    )


class _FakeDataProvider:
    def __init__(self, ctx: BarContext | None = None, exc: Exception | None = None) -> None:
        self.ctx = ctx
        self.exc = exc
        self.calls: list[dict[str, object]] = []

    async def build_context(
        self,
        symbols: Sequence[str],
        *,
        n_bars: int = 1,
        run_id: str = "live",
        factor_names: Sequence[str] | None = None,
        extra_freqs: Sequence[str] | None = None,
        strategy_id: str | None = None,
    ) -> BarContext | None:
        self.calls.append(
            {
                "symbols": list(symbols),
                "n_bars": n_bars,
                "run_id": run_id,
                "factor_names": factor_names,
                "extra_freqs": extra_freqs,
                "strategy_id": strategy_id,
            }
        )
        if self.exc is not None:
            raise self.exc
        return self.ctx


class _FakeSignalWriter:
    def __init__(self, codes: list[str] | None = None, exc: Exception | None = None) -> None:
        self.codes = codes or []
        self.exc = exc
        self.calls: list[tuple[list[Signal], str]] = []

    async def write_batch(self, signals: list[Signal], strategy_id: str) -> list[str]:
        self.calls.append((signals, strategy_id))
        if self.exc is not None:
            raise self.exc
        return self.codes


class _BuyStrategy(Strategy):
    def on_bar(self, ctx: BarContext) -> Iterable[OrderIntent] | None:
        return [OrderIntent(symbol="A", side=Side.BUY, qty=Decimal("100"))]


class _NoSignalStrategy(Strategy):
    def on_bar(self, ctx: BarContext) -> Iterable[OrderIntent] | None:
        return None


def _run(coro: object) -> object:
    import asyncio

    return asyncio.new_event_loop().run_until_complete(coro)  # type: ignore[arg-type]


class TestLiveSignalRunner:
    def test_run_once_writes_produced_signals(self) -> None:
        provider = _FakeDataProvider(_bar_ctx())
        writer = _FakeSignalWriter(["SIG_20260601_ABCDEF"])
        runner = LiveSignalRunner(
            _BuyStrategy(),
            strategy_id="strategy-1",
            data_provider=provider,  # type: ignore[arg-type]
            signal_writer=writer,
            n_bars=3,
        )

        result = _run(runner.run_once(["A"]))

        assert result.n_signals == 1
        assert result.signal_codes == ["SIG_20260601_ABCDEF"]
        assert result.error is None
        assert provider.calls[0]["symbols"] == ["A"]
        assert provider.calls[0]["n_bars"] == 3
        assert provider.calls[0]["run_id"] == "live-strategy-1"
        assert len(writer.calls) == 1
        signals, strategy_id = writer.calls[0]
        assert strategy_id == "strategy-1"
        assert signals[0].symbol == "A"
        assert signals[0].action == "buy"

    def test_no_bars_returns_zero_and_does_not_write(self) -> None:
        provider = _FakeDataProvider(None)
        writer = _FakeSignalWriter()
        runner = LiveSignalRunner(
            _BuyStrategy(),
            strategy_id="strategy-1",
            data_provider=provider,  # type: ignore[arg-type]
            signal_writer=writer,
        )

        result = _run(runner.run_once(["A"]))

        assert result.n_signals == 0
        assert result.signal_codes == []
        assert result.error is None
        assert writer.calls == []

    def test_no_strategy_output_returns_zero_and_does_not_write(self) -> None:
        provider = _FakeDataProvider(_bar_ctx())
        writer = _FakeSignalWriter()
        runner = LiveSignalRunner(
            _NoSignalStrategy(),
            strategy_id="strategy-1",
            data_provider=provider,  # type: ignore[arg-type]
            signal_writer=writer,
        )

        result = _run(runner.run_once(["A"]))

        assert result.n_signals == 0
        assert result.signal_codes == []
        assert result.error is None
        assert writer.calls == []

    def test_data_provider_error_returns_error_result(self) -> None:
        provider = _FakeDataProvider(exc=LiveDataError("clickhouse down"))
        writer = _FakeSignalWriter()
        runner = LiveSignalRunner(
            _BuyStrategy(),
            strategy_id="strategy-1",
            data_provider=provider,  # type: ignore[arg-type]
            signal_writer=writer,
        )

        result = _run(runner.run_once(["A"]))

        assert result.n_signals == 0
        assert result.signal_codes == []
        assert "clickhouse down" in str(result.error)
        assert writer.calls == []

    def test_writer_error_returns_error_result(self) -> None:
        provider = _FakeDataProvider(_bar_ctx())
        writer = _FakeSignalWriter(exc=RuntimeError("postgres down"))
        runner = LiveSignalRunner(
            _BuyStrategy(),
            strategy_id="strategy-1",
            data_provider=provider,  # type: ignore[arg-type]
            signal_writer=writer,
        )

        result = _run(runner.run_once(["A"]))

        assert result.n_signals == 0
        assert result.signal_codes == []
        assert "postgres down" in str(result.error)
        assert len(writer.calls) == 1

    def test_constructor_rejects_invalid_strategy_id(self) -> None:
        with pytest.raises(ValueError, match="strategy_id"):
            LiveSignalRunner(_BuyStrategy(), strategy_id="")

    def test_constructor_rejects_invalid_n_bars(self) -> None:
        with pytest.raises(ValueError, match="n_bars"):
            LiveSignalRunner(_BuyStrategy(), strategy_id="strategy-1", n_bars=0)


# ---------------------------------------------------------------------------
# Factor auto-discovery in runner
# ---------------------------------------------------------------------------


class _FactorStrategy(Strategy):
    FACTOR_NAMES = ["mom20", "rs_14"]

    def on_bar(self, ctx: BarContext) -> Iterable[OrderIntent] | None:
        return [OrderIntent(symbol="A", side=Side.BUY, qty=Decimal("100"))]


class _EmptyFactorStrategy(Strategy):
    FACTOR_NAMES: list[str] = []

    def on_bar(self, ctx: BarContext) -> Iterable[OrderIntent] | None:
        return None


class TestLiveSignalRunnerFactorDiscovery:
    def test_auto_discovers_factor_names_from_strategy(self) -> None:
        """Strategy with FACTOR_NAMES attribute passes them to build_context."""
        provider = _FakeDataProvider(_bar_ctx())
        writer = _FakeSignalWriter(["SIG_A"])
        runner = LiveSignalRunner(
            _FactorStrategy(),
            strategy_id="strategy-1",
            data_provider=provider,  # type: ignore[arg-type]
            signal_writer=writer,
        )

        _run(runner.run_once(["A"]))

        assert provider.calls[0]["factor_names"] == ["mom20", "rs_14"]

    def test_no_factor_names_when_not_declared(self) -> None:
        """Strategy without FACTOR_NAMES passes factor_names=None."""
        provider = _FakeDataProvider(_bar_ctx())
        writer = _FakeSignalWriter(["SIG_A"])
        runner = LiveSignalRunner(
            _BuyStrategy(),
            strategy_id="strategy-1",
            data_provider=provider,  # type: ignore[arg-type]
            signal_writer=writer,
        )

        _run(runner.run_once(["A"]))

        assert provider.calls[0]["factor_names"] is None

    def test_empty_factor_names_not_passed(self) -> None:
        """FACTOR_NAMES=[] is normalized to None (no factor_names passed)."""
        provider = _FakeDataProvider(_bar_ctx())
        writer = _FakeSignalWriter([])
        runner = LiveSignalRunner(
            _EmptyFactorStrategy(),
            strategy_id="strategy-1",
            data_provider=provider,  # type: ignore[arg-type]
            signal_writer=writer,
        )

        _run(runner.run_once(["A"]))

        assert provider.calls[0]["factor_names"] is None

    def test_explicit_factor_names_override_strategy_declaration(self) -> None:
        """Explicit run_once(factor_names=['a']) overrides FACTOR_NAMES."""
        provider = _FakeDataProvider(_bar_ctx())
        writer = _FakeSignalWriter(["SIG_A"])
        runner = LiveSignalRunner(
            _FactorStrategy(),
            strategy_id="strategy-1",
            data_provider=provider,  # type: ignore[arg-type]
            signal_writer=writer,
        )

        _run(runner.run_once(["A"], factor_names=["custom_factor"]))

        assert provider.calls[0]["factor_names"] == ["custom_factor"]

    def test_explicit_none_factor_names_uses_strategy_declaration(self) -> None:
        """run_once(factor_names=None) falls back to strategy FACTOR_NAMES."""
        provider = _FakeDataProvider(_bar_ctx())
        writer = _FakeSignalWriter(["SIG_A"])
        runner = LiveSignalRunner(
            _FactorStrategy(),
            strategy_id="strategy-1",
            data_provider=provider,  # type: ignore[arg-type]
            signal_writer=writer,
        )

        _run(runner.run_once(["A"], factor_names=None))

        assert provider.calls[0]["factor_names"] == ["mom20", "rs_14"]


# ---------------------------------------------------------------------------
# Extra freq auto-discovery in runner
# ---------------------------------------------------------------------------


class _MultiFreqStrategy(Strategy):
    EXTRA_FREQS = ("5m", "1d")

    def on_bar(self, ctx: BarContext) -> Iterable[OrderIntent] | None:
        return [OrderIntent(symbol="A", side=Side.BUY, qty=Decimal("100"))]


class _EmptyExtraFreqStrategy(Strategy):
    EXTRA_FREQS: list[str] = []

    def on_bar(self, ctx: BarContext) -> Iterable[OrderIntent] | None:
        return None


class TestLiveSignalRunnerExtraFreqDiscovery:
    def test_auto_discovers_extra_freqs(self) -> None:
        """Strategy with EXTRA_FREQS passes them to build_context."""
        provider = _FakeDataProvider(_bar_ctx())
        writer = _FakeSignalWriter(["SIG_A"])
        runner = LiveSignalRunner(
            _MultiFreqStrategy(),
            strategy_id="strategy-1",
            data_provider=provider,  # type: ignore[arg-type]
            signal_writer=writer,
        )

        _run(runner.run_once(["A"]))

        assert provider.calls[0]["extra_freqs"] == ("5m", "1d")

    def test_no_extra_freqs_when_not_declared(self) -> None:
        """Strategy without EXTRA_FREQS passes extra_freqs=None."""
        provider = _FakeDataProvider(_bar_ctx())
        writer = _FakeSignalWriter(["SIG_A"])
        runner = LiveSignalRunner(
            _BuyStrategy(),
            strategy_id="strategy-1",
            data_provider=provider,  # type: ignore[arg-type]
            signal_writer=writer,
        )

        _run(runner.run_once(["A"]))

        assert provider.calls[0]["extra_freqs"] is None

    def test_empty_extra_freqs_not_passed(self) -> None:
        """EXTRA_FREQS=[] is normalized to None."""
        provider = _FakeDataProvider(_bar_ctx())
        writer = _FakeSignalWriter([])
        runner = LiveSignalRunner(
            _EmptyExtraFreqStrategy(),
            strategy_id="strategy-1",
            data_provider=provider,  # type: ignore[arg-type]
            signal_writer=writer,
        )

        _run(runner.run_once(["A"]))

        assert provider.calls[0]["extra_freqs"] is None

    def test_explicit_extra_freqs_override_strategy_declaration(self) -> None:
        """run_once(extra_freqs=['1h']) overrides EXTRA_FREQS."""
        provider = _FakeDataProvider(_bar_ctx())
        writer = _FakeSignalWriter(["SIG_A"])
        runner = LiveSignalRunner(
            _MultiFreqStrategy(),
            strategy_id="strategy-1",
            data_provider=provider,  # type: ignore[arg-type]
            signal_writer=writer,
        )

        _run(runner.run_once(["A"], extra_freqs=["1h"]))

        assert provider.calls[0]["extra_freqs"] == ["1h"]

    def test_explicit_none_extra_freqs_uses_strategy_declaration(self) -> None:
        """run_once(extra_freqs=None) falls back to strategy EXTRA_FREQS."""
        provider = _FakeDataProvider(_bar_ctx())
        writer = _FakeSignalWriter(["SIG_A"])
        runner = LiveSignalRunner(
            _MultiFreqStrategy(),
            strategy_id="strategy-1",
            data_provider=provider,  # type: ignore[arg-type]
            signal_writer=writer,
        )

        _run(runner.run_once(["A"], extra_freqs=None))

        assert provider.calls[0]["extra_freqs"] == ("5m", "1d")
