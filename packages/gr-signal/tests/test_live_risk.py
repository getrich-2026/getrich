"""Tests for live risk monitoring and alerting."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from logging import LogRecord

import polars as pl
import pytest
from gr_backtest import get_shanghai_tz
from gr_backtest.exceptions import TimezoneError
from gr_backtest.risk import RiskConfig
from gr_backtest.strategy import Strategy
from gr_backtest.strategy.context import (
    AccountView,
    BarContext,
    HistoryView,
    PositionView,
)
from gr_backtest.strategy.order import OrderIntent
from gr_backtest.types import Side
from gr_signal.live_risk import (
    EmailAlertChannel,
    LiveRiskMonitor,
    LoggingAlertChannel,
    RiskAlert,
    WebhookAlertChannel,
    _compute_equity,
    _compute_gross_exposure,
)
from gr_signal.live_runner import LiveSignalRunner, _extract_last_prices


TZ = get_shanghai_tz()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ts() -> datetime:
    return datetime(2026, 6, 1, 9, 30, tzinfo=TZ)


def _bar_ctx(
    cash: Decimal = Decimal("100000"),
    positions: dict[str, PositionView] | None = None,
    available_cash: Decimal | None = None,
    maintenance_margin: Decimal = Decimal("0"),
    close_prices: dict[str, float] | None = None,
) -> BarContext:
    now = _make_ts()
    symbols = list((positions or {}).keys()) or ["A"]
    if close_prices is None:
        close_prices = {s: 10.0 for s in symbols}

    data: dict[str, list] = {
        "dt": [now] * len(close_prices),
        "symbol": list(close_prices.keys()),
        "open": [10.0] * len(close_prices),
        "high": [10.2] * len(close_prices),
        "low": [9.9] * len(close_prices),
        "close": list(close_prices.values()),
        "volume": [1000.0] * len(close_prices),
    }
    bar = pl.DataFrame(
        data,
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )
    return BarContext(
        now=now,
        run_id="live-test",
        account=AccountView(
            cash=cash,
            positions=positions,
            available_cash=available_cash,
            maintenance_margin=maintenance_margin,
        ),
        bar=bar,
        history=HistoryView(bar),
    )


class _FakeAlertChannel:
    """Captures alerts for testing."""

    def __init__(self) -> None:
        self.sent: list[RiskAlert] = []

    async def send(self, alert: RiskAlert) -> None:
        self.sent.append(alert)


class _FailingAlertChannel:
    """Alert channel that always raises."""

    async def send(self, alert: RiskAlert) -> None:
        raise RuntimeError("channel failure")


# ---------------------------------------------------------------------------
# RiskAlert
# ---------------------------------------------------------------------------


class TestRiskAlert:
    def test_construct_valid_risk_alert(self) -> None:
        alert = RiskAlert(
            severity="warning",
            check="margin_call",
            reason="low margin",
            details={"available_cash": "100"},
            triggered_at=_make_ts(),
        )
        assert alert.severity == "warning"
        assert alert.check == "margin_call"
        assert alert.reason == "low margin"
        assert alert.details == {"available_cash": "100"}
        assert alert.triggered_at == _make_ts()

    def test_risk_alert_rejects_invalid_severity(self) -> None:
        with pytest.raises(ValueError, match="severity"):
            RiskAlert(severity="info", check="margin_call", reason="x")

    def test_risk_alert_rejects_empty_check(self) -> None:
        with pytest.raises(ValueError, match="check"):
            RiskAlert(severity="warning", check="", reason="x")

    def test_risk_alert_rejects_empty_reason(self) -> None:
        with pytest.raises(ValueError, match="reason"):
            RiskAlert(severity="warning", check="margin_call", reason="")

    def test_risk_alert_rejects_non_shanghai_tz(self) -> None:
        with pytest.raises(TimezoneError, match="Asia/Shanghai"):
            RiskAlert(
                severity="warning",
                check="margin_call",
                reason="low margin",
                triggered_at=datetime(2026, 6, 1, 9, 30),
            )

    def test_risk_alert_allows_none_triggered_at(self) -> None:
        alert = RiskAlert(severity="warning", check="margin_call", reason="low margin")
        assert alert.triggered_at is None


# ---------------------------------------------------------------------------
# LiveRiskMonitor — margin / liquidation
# ---------------------------------------------------------------------------


class TestLiveRiskMonitorMargin:
    def test_no_violations_returns_empty(self) -> None:
        monitor = LiveRiskMonitor()
        account = AccountView(
            cash=Decimal("100000"),
            available_cash=Decimal("50000"),
            maintenance_margin=Decimal("10000"),
        )
        alerts = monitor.check_account_health(account, {}, now=_make_ts())
        assert alerts == []

    def test_margin_call_triggered(self) -> None:
        """available_cash below margin_call_threshold * maintenance_margin → warning."""
        monitor = LiveRiskMonitor(RiskConfig(margin_call_threshold=Decimal("1.0")))
        account = AccountView(
            cash=Decimal("5000"),
            available_cash=Decimal("8000"),
            maintenance_margin=Decimal("10000"),
        )
        alerts = monitor.check_account_health(account, {}, now=_make_ts())
        assert len(alerts) >= 1
        margin_alerts = [a for a in alerts if a.check == "margin_call"]
        assert len(margin_alerts) >= 1
        assert margin_alerts[0].severity == "warning"

    def test_liquidation_triggered(self) -> None:
        """available_cash below liquidation_threshold * maintenance_margin → critical."""
        monitor = LiveRiskMonitor(RiskConfig(liquidation_threshold=Decimal("0.8")))
        account = AccountView(
            cash=Decimal("5000"),
            available_cash=Decimal("7000"),
            maintenance_margin=Decimal("10000"),
        )
        alerts = monitor.check_account_health(account, {}, now=_make_ts())
        liq_alerts = [a for a in alerts if a.check == "liquidation"]
        assert len(liq_alerts) == 1
        assert liq_alerts[0].severity == "critical"
        # Liquidation also implies margin call
        margin_alerts = [a for a in alerts if a.check == "margin_call"]
        assert len(margin_alerts) == 1

    def test_margin_safe_zero_maintenance(self) -> None:
        """maintenance_margin=0 → no margin check."""
        monitor = LiveRiskMonitor()
        account = AccountView(
            cash=Decimal("1000"),
            available_cash=Decimal("10"),
            maintenance_margin=Decimal("0"),
        )
        alerts = monitor.check_account_health(account, {}, now=_make_ts())
        margin_alerts = [a for a in alerts if a.check in ("margin_call", "liquidation")]
        assert margin_alerts == []

    def test_margin_safe_high_cash(self) -> None:
        """available_cash >> maintenance_margin → safe."""
        monitor = LiveRiskMonitor(RiskConfig(margin_call_threshold=Decimal("1.0")))
        account = AccountView(
            cash=Decimal("100000"),
            available_cash=Decimal("100000"),
            maintenance_margin=Decimal("10000"),
        )
        alerts = monitor.check_account_health(account, {}, now=_make_ts())
        assert alerts == []

    def test_margin_safe_available_cash_none(self) -> None:
        """available_cash=None → no margin check."""
        monitor = LiveRiskMonitor()
        account = AccountView(
            cash=Decimal("5000"),
            available_cash=None,
            maintenance_margin=Decimal("10000"),
        )
        alerts = monitor.check_account_health(account, {}, now=_make_ts())
        assert alerts == []


# ---------------------------------------------------------------------------
# LiveRiskMonitor — leverage
# ---------------------------------------------------------------------------


class TestLiveRiskMonitorLeverage:
    def test_leverage_breached(self) -> None:
        """gross_exposure/equity > max_leverage → critical."""
        monitor = LiveRiskMonitor(RiskConfig(max_leverage=Decimal("2")))
        account = AccountView(
            cash=Decimal("5000"),
            positions={
                "A": PositionView(symbol="A", qty=Decimal("1000")),
            },
        )
        # price=10 → equity = 5000 + 1000*10 = 15000
        # gross_exposure = 1000*10 = 10000 → leverage = 10000/15000 ≈ 0.67 → safe
        last_prices = {"A": Decimal("10")}
        alerts = monitor.check_account_health(account, last_prices, now=_make_ts())
        leverage_alerts = [a for a in alerts if a.check == "leverage"]
        assert leverage_alerts == []

    def test_leverage_breached_high_exposure(self) -> None:
        """High exposure with low equity → leverage breached."""
        monitor = LiveRiskMonitor(RiskConfig(max_leverage=Decimal("2")))
        account = AccountView(
            cash=Decimal("1000"),
            positions={
                "A": PositionView(symbol="A", qty=Decimal("500")),
            },
        )
        # price=10 → equity = 1000 + 500*10 = 6000
        # gross_exposure = 5000 → leverage = 5000/6000 ≈ 0.83 → safe
        alerts = monitor.check_account_health(account, {"A": Decimal("10")}, now=_make_ts())
        assert [a for a in alerts if a.check == "leverage"] == []

    def test_leverage_actually_breached(self) -> None:
        """Short position with low equity triggers leverage alert."""
        monitor = LiveRiskMonitor(RiskConfig(max_leverage=Decimal("2")))
        # Short position: cash from proceeds, equity = cash + short_qty*price
        # cash=6000, short qty=-500 at price=10 → equity=6000-5000=1000
        # gross_exposure = |-500|*10 = 5000 → leverage = 5x > 2x max
        account = AccountView(
            cash=Decimal("6000"),
            positions={
                "A": PositionView(symbol="A", qty=Decimal("-500")),
            },
        )
        alerts = monitor.check_account_health(account, {"A": Decimal("10")}, now=_make_ts())
        leverage_alerts = [a for a in alerts if a.check == "leverage"]
        assert len(leverage_alerts) == 1
        assert leverage_alerts[0].severity == "critical"

    def test_leverage_safe(self) -> None:
        """Leverage within limit → safe."""
        monitor = LiveRiskMonitor(RiskConfig(max_leverage=Decimal("3")))
        account = AccountView(
            cash=Decimal("5000"),
            positions={
                "A": PositionView(symbol="A", qty=Decimal("100")),
            },
        )
        # equity = 5000 + 100*10 = 6000, exposure = 1000, lev = 0.17 < 3
        alerts = monitor.check_account_health(account, {"A": Decimal("10")}, now=_make_ts())
        assert [a for a in alerts if a.check == "leverage"] == []

    def test_leverage_max_leverage_none(self) -> None:
        """max_leverage=None → no leverage check."""
        monitor = LiveRiskMonitor(RiskConfig(max_leverage=None))
        account = AccountView(
            cash=Decimal("1000"),
            positions={
                "A": PositionView(symbol="A", qty=Decimal("10000")),
            },
        )
        alerts = monitor.check_account_health(account, {"A": Decimal("10")}, now=_make_ts())
        assert [a for a in alerts if a.check == "leverage"] == []


# ---------------------------------------------------------------------------
# LiveRiskMonitor — concentration
# ---------------------------------------------------------------------------


class TestLiveRiskMonitorConcentration:
    def test_concentration_breached(self) -> None:
        """Single position > max_concentration → warning per symbol."""
        monitor = LiveRiskMonitor(RiskConfig(max_position_concentration=Decimal("0.3")))
        account = AccountView(
            cash=Decimal("5000"),
            positions={
                "A": PositionView(symbol="A", qty=Decimal("500")),
            },
        )
        # equity = 5000 + 500*10 = 10000, notional = 5000, conc = 0.5 > 0.3
        alerts = monitor.check_account_health(account, {"A": Decimal("10")}, now=_make_ts())
        conc_alerts = [a for a in alerts if a.check == "concentration"]
        assert len(conc_alerts) == 1
        assert conc_alerts[0].severity == "warning"
        assert "A" in str(conc_alerts[0].details.get("symbol", ""))

    def test_concentration_safe(self) -> None:
        """All positions within cap → safe."""
        monitor = LiveRiskMonitor(RiskConfig(max_position_concentration=Decimal("0.8")))
        account = AccountView(
            cash=Decimal("5000"),
            positions={
                "A": PositionView(symbol="A", qty=Decimal("100")),
                "B": PositionView(symbol="B", qty=Decimal("50")),
            },
        )
        # equity = 5000 + 150*10 = 6500, A_notional=1000 → conc=0.15, B_notional=500 → conc=0.08
        alerts = monitor.check_account_health(
            account, {"A": Decimal("10"), "B": Decimal("10")}, now=_make_ts()
        )
        assert [a for a in alerts if a.check == "concentration"] == []

    def test_concentration_max_none(self) -> None:
        """max_position_concentration=None → no concentration check."""
        monitor = LiveRiskMonitor(RiskConfig(max_position_concentration=None))
        account = AccountView(
            cash=Decimal("1000"),
            positions={
                "A": PositionView(symbol="A", qty=Decimal("10000")),
            },
        )
        alerts = monitor.check_account_health(account, {"A": Decimal("10")}, now=_make_ts())
        assert [a for a in alerts if a.check == "concentration"] == []

    def test_concentration_multiple_breaches(self) -> None:
        """Multiple positions over cap → multiple alerts."""
        monitor = LiveRiskMonitor(RiskConfig(max_position_concentration=Decimal("0.2")))
        account = AccountView(
            cash=Decimal("1000"),
            positions={
                "A": PositionView(symbol="A", qty=Decimal("200")),
                "B": PositionView(symbol="B", qty=Decimal("300")),
            },
        )
        # equity = 1000 + 500*10 = 6000
        # A_notional=2000 conc≈0.33, B_notional=3000 conc=0.5
        alerts = monitor.check_account_health(
            account, {"A": Decimal("10"), "B": Decimal("10")}, now=_make_ts()
        )
        conc_alerts = [a for a in alerts if a.check == "concentration"]
        assert len(conc_alerts) == 2

    def test_concentration_symbol_not_in_prices_skipped(self) -> None:
        """Symbol missing from last_prices is skipped in concentration check."""
        monitor = LiveRiskMonitor(RiskConfig(max_position_concentration=Decimal("0.1")))
        account = AccountView(
            cash=Decimal("5000"),
            positions={
                "A": PositionView(symbol="A", qty=Decimal("1000")),
            },
        )
        # A not in last_prices → price=0 → skipped
        alerts = monitor.check_account_health(account, {}, now=_make_ts())
        assert [a for a in alerts if a.check == "concentration"] == []


# ---------------------------------------------------------------------------
# LiveRiskMonitor — multiple violations
# ---------------------------------------------------------------------------


class TestLiveRiskMonitorMultipleViolations:
    def test_multiple_violations(self) -> None:
        """Both margin_call and concentration → multiple alerts."""
        monitor = LiveRiskMonitor(
            RiskConfig(
                margin_call_threshold=Decimal("1.0"),
                max_position_concentration=Decimal("0.3"),
            )
        )
        account = AccountView(
            cash=Decimal("5000"),
            available_cash=Decimal("8000"),
            maintenance_margin=Decimal("10000"),
            positions={
                "A": PositionView(symbol="A", qty=Decimal("500")),
            },
        )
        alerts = monitor.check_account_health(account, {"A": Decimal("10")}, now=_make_ts())
        # Should have at least margin_call (available_cash < maintenance) and concentration
        alert_types = {a.check for a in alerts}
        assert "margin_call" in alert_types
        assert "concentration" in alert_types


# ---------------------------------------------------------------------------
# LoggingAlertChannel
# ---------------------------------------------------------------------------


class TestLoggingAlertChannel:
    def test_sends_warning_alert_to_logger(self) -> None:
        channel = LoggingAlertChannel(name="test.risk.warning")
        from gr_signal.live_risk import RiskAlert

        alert = RiskAlert(
            severity="warning",
            check="margin_call",
            reason="low margin",
            triggered_at=_make_ts(),
        )

        # Capture log
        with _capture_logs("test.risk.warning", logging.WARNING) as records:
            import asyncio

            asyncio.new_event_loop().run_until_complete(channel.send(alert))

        assert len(records) == 1
        assert records[0].levelno == logging.WARNING
        assert "margin_call" in records[0].getMessage()
        assert "low margin" in records[0].getMessage()

    def test_sends_critical_alert_to_logger(self) -> None:
        channel = LoggingAlertChannel(name="test.risk.critical")
        alert = RiskAlert(
            severity="critical",
            check="liquidation",
            reason="below liquidation threshold",
            triggered_at=_make_ts(),
        )

        with _capture_logs("test.risk.critical", logging.ERROR) as records:
            import asyncio

            asyncio.new_event_loop().run_until_complete(channel.send(alert))

        assert len(records) == 1
        assert records[0].levelno == logging.ERROR
        assert "liquidation" in records[0].getMessage()

    def test_alert_details_in_log_extra(self) -> None:
        channel = LoggingAlertChannel(name="test.risk.details")
        alert = RiskAlert(
            severity="warning",
            check="margin_call",
            reason="low margin",
            details={"ratio": "0.5", "threshold": "1.0"},
            triggered_at=_make_ts(),
        )

        with _capture_logs("test.risk.details", logging.WARNING) as records:
            import asyncio

            asyncio.new_event_loop().run_until_complete(channel.send(alert))

        assert len(records) == 1
        assert hasattr(records[0], "risk_alert_details")
        assert records[0].risk_alert_details == {"ratio": "0.5", "threshold": "1.0"}  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# send_alerts — channel isolation
# ---------------------------------------------------------------------------


class TestSendAlerts:
    def test_send_alerts_distributes_to_all_channels(self) -> None:
        ch1 = _FakeAlertChannel()
        ch2 = _FakeAlertChannel()
        monitor = LiveRiskMonitor(channels=[ch1, ch2])
        alert = RiskAlert(
            severity="warning",
            check="margin_call",
            reason="low margin",
            triggered_at=_make_ts(),
        )

        import asyncio

        asyncio.new_event_loop().run_until_complete(monitor.send_alerts([alert]))
        assert len(ch1.sent) == 1
        assert len(ch2.sent) == 1

    def test_send_alerts_failing_channel_does_not_affect_others(self) -> None:
        ch1 = _FakeAlertChannel()
        ch2 = _FailingAlertChannel()
        monitor = LiveRiskMonitor(channels=[ch1, ch2])
        alert = RiskAlert(
            severity="warning",
            check="margin_call",
            reason="low margin",
            triggered_at=_make_ts(),
        )

        import asyncio

        asyncio.new_event_loop().run_until_complete(monitor.send_alerts([alert]))
        # ch2 raised → ch1 should still receive
        assert len(ch1.sent) == 1


# ---------------------------------------------------------------------------
# _compute_equity / _compute_gross_exposure helpers
# ---------------------------------------------------------------------------


class TestComputeEquity:
    def test_equity_cash_only(self) -> None:
        account = AccountView(cash=Decimal("100000"))
        assert _compute_equity(account, {}) == Decimal("100000")

    def test_equity_with_positions(self) -> None:
        account = AccountView(
            cash=Decimal("10000"),
            positions={
                "A": PositionView(symbol="A", qty=Decimal("100")),
                "B": PositionView(symbol="B", qty=Decimal("-50")),
            },
        )
        prices = {"A": Decimal("10"), "B": Decimal("20")}
        # equity = 10000 + 100*10 + (-50)*20 = 10000 + 1000 - 1000 = 10000
        assert _compute_equity(account, prices) == Decimal("10000")

    def test_equity_missing_price_treated_as_zero(self) -> None:
        account = AccountView(
            cash=Decimal("10000"),
            positions={"A": PositionView(symbol="A", qty=Decimal("100"))},
        )
        assert _compute_equity(account, {}) == Decimal("10000")

    def test_gross_exposure_empty(self) -> None:
        account = AccountView(cash=Decimal("10000"))
        assert _compute_gross_exposure(account, {}) == Decimal("0")

    def test_gross_exposure_with_positions(self) -> None:
        account = AccountView(
            cash=Decimal("10000"),
            positions={
                "A": PositionView(symbol="A", qty=Decimal("100")),
                "B": PositionView(symbol="B", qty=Decimal("-50")),
            },
        )
        prices = {"A": Decimal("10"), "B": Decimal("20")}
        # gross = |100*10| + |-50*20| = 1000 + 1000 = 2000
        assert _compute_gross_exposure(account, prices) == Decimal("2000")


# ---------------------------------------------------------------------------
# _extract_last_prices
# ---------------------------------------------------------------------------


class TestExtractLastPrices:
    def test_extracts_close_prices(self) -> None:
        bar = pl.DataFrame(
            {
                "dt": [_make_ts(), _make_ts()],
                "symbol": ["A", "B"],
                "open": [10.0, 20.0],
                "high": [10.2, 20.2],
                "low": [9.9, 19.9],
                "close": [10.1, 20.1],
                "volume": [1000.0, 2000.0],
            },
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )
        prices = _extract_last_prices(bar)
        assert prices == {
            "A": Decimal("10.1"),
            "B": Decimal("20.1"),
        }


# ---------------------------------------------------------------------------
# LiveSignalRunner risk integration
# ---------------------------------------------------------------------------


# Re-use fakes from the live_runner tests adapted for risk
class _FakeDataProvider:
    def __init__(self, ctx: BarContext | None = None, exc: Exception | None = None) -> None:
        self.ctx = ctx
        self.exc = exc
        self.calls: list[dict] = []

    async def build_context(
        self,
        symbols,
        *,
        n_bars=1,
        run_id="live",
        factor_names=None,
        extra_freqs=None,
        strategy_id=None,
    ):
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
    def __init__(self, codes=None, exc=None):
        self.codes = codes or []
        self.exc = exc
        self.calls: list = []

    async def write_batch(self, signals, strategy_id):
        self.calls.append((signals, strategy_id))
        if self.exc is not None:
            raise self.exc
        return self.codes


class _BuyStrategy(Strategy):
    def on_bar(self, ctx: BarContext):
        return [OrderIntent(symbol="A", side=Side.BUY, qty=Decimal("100"))]


class _NoSignalStrategy(Strategy):
    def on_bar(self, ctx: BarContext):
        return None


def _run(coro):
    import asyncio

    return asyncio.new_event_loop().run_until_complete(coro)


class TestLiveSignalRunnerRiskIntegration:
    def test_risk_check_blocks_signals_on_critical(self) -> None:
        """Critical risk alert (liquidation) blocks signal production."""
        ctx = _bar_ctx(
            cash=Decimal("5000"),
            available_cash=Decimal("7000"),
            maintenance_margin=Decimal("10000"),
        )
        provider = _FakeDataProvider(ctx)
        writer = _FakeSignalWriter()

        risk_config = RiskConfig(liquidation_threshold=Decimal("0.8"))
        runner = LiveSignalRunner(
            _BuyStrategy(),
            strategy_id="strategy-1",
            data_provider=provider,  # type: ignore[arg-type]
            signal_writer=writer,
            risk_config=risk_config,
        )

        result = _run(runner.run_once(["A"]))

        # Signals are blocked — no write happened
        assert result.n_signals == 0
        assert result.signal_codes == []
        assert result.error is not None
        assert "risk blocked" in str(result.error)
        assert "liquidation" in str(result.error)
        assert writer.calls == []

    def test_risk_check_allows_signals_when_safe(self) -> None:
        """Healthy account → signals produced normally."""
        ctx = _bar_ctx(
            cash=Decimal("100000"),
            available_cash=Decimal("50000"),
            maintenance_margin=Decimal("10000"),
        )
        provider = _FakeDataProvider(ctx)
        writer = _FakeSignalWriter(["SIG_OK"])

        risk_config = RiskConfig(
            margin_call_threshold=Decimal("1.0"),
            liquidation_threshold=Decimal("0.8"),
        )
        runner = LiveSignalRunner(
            _BuyStrategy(),
            strategy_id="strategy-1",
            data_provider=provider,  # type: ignore[arg-type]
            signal_writer=writer,
            risk_config=risk_config,
        )

        result = _run(runner.run_once(["A"]))

        assert result.n_signals == 1
        assert result.signal_codes == ["SIG_OK"]
        assert result.error is None
        assert len(writer.calls) == 1

    def test_no_risk_monitor_no_checks(self) -> None:
        """With risk_config=None, signals flow through unchanged."""
        ctx = _bar_ctx(
            cash=Decimal("5000"),
            available_cash=Decimal("100"),
            maintenance_margin=Decimal("10000"),
        )
        provider = _FakeDataProvider(ctx)
        writer = _FakeSignalWriter(["SIG_OK"])

        runner = LiveSignalRunner(
            _BuyStrategy(),
            strategy_id="strategy-1",
            data_provider=provider,  # type: ignore[arg-type]
            signal_writer=writer,
            risk_config=None,
        )

        result = _run(runner.run_once(["A"]))
        assert result.n_signals == 1
        assert result.error is None

    def test_warning_only_does_not_block(self) -> None:
        """Warning alerts (margin_call) log but don't block signals."""
        ctx = _bar_ctx(
            cash=Decimal("100000"),
            available_cash=Decimal("9000"),
            maintenance_margin=Decimal("10000"),
            positions={
                "A": PositionView(symbol="A", qty=Decimal("500")),
            },
        )
        provider = _FakeDataProvider(ctx)
        writer = _FakeSignalWriter(["SIG_OK"])

        risk_config = RiskConfig(
            margin_call_threshold=Decimal("1.0"),
            liquidation_threshold=Decimal("0.8"),
            max_position_concentration=Decimal("0.3"),
        )
        runner = LiveSignalRunner(
            _BuyStrategy(),
            strategy_id="strategy-1",
            data_provider=provider,  # type: ignore[arg-type]
            signal_writer=writer,
            risk_config=risk_config,
        )

        result = _run(runner.run_once(["A"]))

        # Warning only — signals should still flow
        assert result.n_signals == 1
        assert result.error is None
        assert len(writer.calls) == 1

    def test_risk_check_with_alert_channels(self) -> None:
        """Alert channels receive risk alerts during the cycle."""
        ctx = _bar_ctx(
            cash=Decimal("5000"),
            available_cash=Decimal("7000"),
            maintenance_margin=Decimal("10000"),
        )
        provider = _FakeDataProvider(ctx)
        writer = _FakeSignalWriter()

        channel = _FakeAlertChannel()
        risk_config = RiskConfig(liquidation_threshold=Decimal("0.8"))
        runner = LiveSignalRunner(
            _BuyStrategy(),
            strategy_id="strategy-1",
            data_provider=provider,  # type: ignore[arg-type]
            signal_writer=writer,
            risk_config=risk_config,
            alert_channels=[channel],
        )

        _run(runner.run_once(["A"]))

        # Channel should have received the alerts
        assert len(channel.sent) > 0
        assert any(a.severity == "critical" for a in channel.sent)


# ---------------------------------------------------------------------------
# Log capture helper
# ---------------------------------------------------------------------------


@contextmanager
def _capture_logs(logger_name: str, level: int = logging.DEBUG) -> Iterator[list[LogRecord]]:
    """Capture log records emitted to *logger_name*."""
    log = logging.getLogger(logger_name)
    log.setLevel(level)

    records: list[LogRecord] = []

    class _TestHandler(logging.Handler):
        def emit(self, record: LogRecord) -> None:
            records.append(record)

    handler = _TestHandler()
    handler.setLevel(level)
    log.addHandler(handler)

    try:
        yield records
    finally:
        log.removeHandler(handler)


# ============================================================================
# WebhookAlertChannel tests
# ============================================================================


class TestWebhookAlertChannelSerialization:
    """Serialization helper produces valid JSON-serialisable dict."""

    def test_basic_serialization(self) -> None:
        alert = RiskAlert(
            severity="warning",
            check="margin_call",
            reason="low margin",
            triggered_at=_make_ts(),
        )
        data = WebhookAlertChannel._serialize(alert)

        assert data["severity"] == "warning"
        assert data["check"] == "margin_call"
        assert data["reason"] == "low margin"
        assert data["details"] == {}
        assert "T" in str(data["triggered_at"])

    def test_serialization_with_details(self) -> None:
        alert = RiskAlert(
            severity="critical",
            check="liquidation",
            reason="below threshold",
            details={"ratio": "0.3", "threshold": "0.8"},
            triggered_at=_make_ts(),
        )
        data = WebhookAlertChannel._serialize(alert)

        assert data["severity"] == "critical"
        assert data["details"] == {"ratio": "0.3", "threshold": "0.8"}

    def test_serialization_null_triggered_at(self) -> None:
        alert = RiskAlert(
            severity="warning",
            check="margin_call",
            reason="low margin",
            triggered_at=None,
        )
        data = WebhookAlertChannel._serialize(alert)

        assert data["triggered_at"] is None


class TestWebhookAlertChannelSend:
    """Webhook delivery calls urllib with correct payload and headers."""

    def test_successful_post(self) -> None:
        from unittest.mock import MagicMock, patch

        url = "https://hooks.example.com/alert"
        channel = WebhookAlertChannel(url, timeout=5.0)

        alert = RiskAlert(
            severity="warning",
            check="margin_call",
            reason="low margin",
            triggered_at=_make_ts(),
        )

        mock_urlopen = MagicMock()
        with patch("urllib.request.urlopen", mock_urlopen):
            import asyncio

            asyncio.new_event_loop().run_until_complete(channel.send(alert))

        # urlopen was called once
        assert mock_urlopen.call_count == 1

    def test_default_content_type_header(self) -> None:
        from unittest.mock import MagicMock, patch

        channel = WebhookAlertChannel("https://hooks.example.com/alert")

        alert = RiskAlert(
            severity="warning",
            check="margin_call",
            reason="low margin",
            triggered_at=_make_ts(),
        )

        mock_urlopen = MagicMock()
        with patch("urllib.request.urlopen", mock_urlopen):
            import asyncio

            asyncio.new_event_loop().run_until_complete(channel.send(alert))

        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Content-type") is not None

    def test_custom_headers_merged(self) -> None:
        from unittest.mock import MagicMock, patch

        channel = WebhookAlertChannel(
            "https://hooks.example.com/alert",
            headers={"X-Signature": "abc123", "Content-Type": "application/x-custom"},
        )

        alert = RiskAlert(
            severity="warning",
            check="margin_call",
            reason="low margin",
            triggered_at=_make_ts(),
        )

        mock_urlopen = MagicMock()
        with patch("urllib.request.urlopen", mock_urlopen):
            import asyncio

            asyncio.new_event_loop().run_until_complete(channel.send(alert))

        req = mock_urlopen.call_args[0][0]
        assert req.get_header("X-signature") == "abc123"

    def test_failure_is_logged_not_raised(self) -> None:
        from unittest.mock import patch

        channel = WebhookAlertChannel("https://hooks.example.com/alert")
        alert = RiskAlert(
            severity="warning",
            check="margin_call",
            reason="low margin",
            triggered_at=_make_ts(),
        )

        # Simulate HTTP failure
        with (
            patch("urllib.request.urlopen", side_effect=OSError("connection refused")),
            _capture_logs("gr_signal.live_risk.webhook", logging.WARNING) as records,
        ):
            import asyncio

            # Should NOT raise
            asyncio.new_event_loop().run_until_complete(channel.send(alert))

        assert len(records) >= 1
        assert any("Webhook delivery" in r.getMessage() for r in records)


class TestWebhookAlertChannelProtocol:
    """WebhookAlertChannel satisfies AlertChannel."""

    def test_satisfies_protocol(self) -> None:
        from gr_signal.live_risk import AlertChannel

        assert isinstance(WebhookAlertChannel("https://example.com/"), AlertChannel)


# ============================================================================
# EmailAlertChannel tests
# ============================================================================


class TestEmailAlertChannelMessage:
    """Email body construction produces a well-formed MIME message."""

    def test_message_subject_and_body(self) -> None:
        channel = EmailAlertChannel(
            "smtp.example.com",
            username="user",
            password="pass",
            from_addr="alert@example.com",
            to_addrs=["trader@example.com"],
        )
        alert = RiskAlert(
            severity="critical",
            check="liquidation",
            reason="below liquidation threshold",
            triggered_at=_make_ts(),
        )
        msg = channel._build_message(alert)

        assert "Subject:" in msg
        assert "CRITICAL" in msg
        assert "liquidation" in msg
        assert "below liquidation threshold" in msg
        assert "From: alert@example.com" in msg
        assert "To: trader@example.com" in msg

    def test_message_with_details(self) -> None:
        channel = EmailAlertChannel(
            "smtp.example.com",
            username="user",
            password="pass",
            from_addr="alert@example.com",
            to_addrs=["trader@example.com"],
        )
        alert = RiskAlert(
            severity="warning",
            check="leverage",
            reason="leverage too high",
            details={"leverage": "3.5", "max_leverage": "2.0"},
            triggered_at=_make_ts(),
        )
        msg = channel._build_message(alert)

        assert "leverage: 3.5" in msg
        assert "max_leverage: 2.0" in msg

    def test_message_multiple_recipients(self) -> None:
        channel = EmailAlertChannel(
            "smtp.example.com",
            username="user",
            password="pass",
            from_addr="alert@example.com",
            to_addrs=["a@example.com", "b@example.com"],
        )
        alert = RiskAlert(
            severity="warning",
            check="margin_call",
            reason="low margin",
            triggered_at=_make_ts(),
        )
        msg = channel._build_message(alert)

        assert "To: a@example.com, b@example.com" in msg

    def test_message_no_triggered_at(self) -> None:
        channel = EmailAlertChannel(
            "smtp.example.com",
            username="user",
            password="pass",
            from_addr="alert@example.com",
            to_addrs=["trader@example.com"],
        )
        alert = RiskAlert(
            severity="warning",
            check="margin_call",
            reason="low margin",
            triggered_at=None,
        )
        msg = channel._build_message(alert)

        assert "Triggered:" not in msg


class TestEmailAlertChannelSend:
    """SMTP delivery calls smtplib with correct parameters."""

    def test_successful_delivery(self) -> None:
        from unittest.mock import MagicMock, patch

        channel = EmailAlertChannel(
            "smtp.example.com",
            smtp_port=587,
            username="user",
            password="pass",
            from_addr="alert@example.com",
            to_addrs=["trader@example.com"],
        )

        alert = RiskAlert(
            severity="critical",
            check="liquidation",
            reason="below threshold",
            triggered_at=_make_ts(),
        )

        mock_smtp = MagicMock()
        with patch("smtplib.SMTP", return_value=mock_smtp):
            import asyncio

            asyncio.new_event_loop().run_until_complete(channel.send(alert))

        # starttls should be called (default TLS mode)
        mock_smtp.starttls.assert_called_once()
        mock_smtp.login.assert_called_once_with("user", "pass")
        mock_smtp.sendmail.assert_called_once()
        mock_smtp.quit.assert_called_once()

    def test_ssl_mode_skips_starttls(self) -> None:
        from unittest.mock import MagicMock, patch

        channel = EmailAlertChannel(
            "smtp.example.com",
            smtp_port=465,
            username="user",
            password="pass",
            from_addr="alert@example.com",
            to_addrs=["trader@example.com"],
            use_tls=False,
        )

        alert = RiskAlert(
            severity="critical",
            check="liquidation",
            reason="below threshold",
            triggered_at=_make_ts(),
        )

        mock_smtp = MagicMock()
        with patch("smtplib.SMTP_SSL", return_value=mock_smtp):
            import asyncio

            asyncio.new_event_loop().run_until_complete(channel.send(alert))

        # SMTP_SSL used, starttls NOT called
        mock_smtp.starttls.assert_not_called()
        mock_smtp.login.assert_called_once_with("user", "pass")
        mock_smtp.sendmail.assert_called_once()
        mock_smtp.quit.assert_called_once()

    def test_sendmail_args_correct(self) -> None:
        from unittest.mock import MagicMock, patch

        channel = EmailAlertChannel(
            "smtp.example.com",
            username="user",
            password="pass",
            from_addr="alert@example.com",
            to_addrs=["a@x.com", "b@x.com"],
        )

        alert = RiskAlert(
            severity="warning",
            check="margin_call",
            reason="low margin",
            triggered_at=_make_ts(),
        )

        mock_smtp = MagicMock()
        with patch("smtplib.SMTP", return_value=mock_smtp):
            import asyncio

            asyncio.new_event_loop().run_until_complete(channel.send(alert))

        args = mock_smtp.sendmail.call_args
        assert args[0][0] == "alert@example.com"  # from_addr
        assert args[0][1] == ["a@x.com", "b@x.com"]  # to_addrs
        assert isinstance(args[0][2], bytes)  # message as bytes

    def test_failure_is_logged_not_raised(self) -> None:
        from unittest.mock import patch

        channel = EmailAlertChannel(
            "smtp.example.com",
            username="user",
            password="pass",
            from_addr="alert@example.com",
            to_addrs=["trader@example.com"],
        )

        alert = RiskAlert(
            severity="critical",
            check="liquidation",
            reason="below threshold",
            triggered_at=_make_ts(),
        )

        with (
            patch("smtplib.SMTP", side_effect=OSError("connection refused")),
            _capture_logs("gr_signal.live_risk.email", logging.WARNING) as records,
        ):
            import asyncio

            # Should NOT raise
            asyncio.new_event_loop().run_until_complete(channel.send(alert))

        assert len(records) >= 1
        assert any("Email delivery" in r.getMessage() for r in records)


class TestEmailAlertChannelProtocol:
    """EmailAlertChannel satisfies AlertChannel."""

    def test_satisfies_protocol(self) -> None:
        from gr_signal.live_risk import AlertChannel

        assert isinstance(
            EmailAlertChannel(
                "smtp.example.com",
                username="user",
                password="pass",
                from_addr="a@x.com",
                to_addrs=["b@x.com"],
            ),
            AlertChannel,
        )
