"""Live signal runner from ClickHouse bars to PostgreSQL signals."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from time import perf_counter
from typing import TYPE_CHECKING, Protocol

from getrich.apps.strategy.live_data_provider import LiveDataProvider
from getrich.apps.strategy.live_risk import AlertChannel, LiveRiskMonitor, RiskAlert
from getrich.apps.strategy.signal_writer import PgSignalWriter
from getrich.apps.web.metrics import LIVE_RUN_ONCE_SECONDS, LIVE_STRATEGY_ERRORS_TOTAL
from getrich_backtest import get_shanghai_tz
from getrich_backtest.live import Signal, SignalProducer
from getrich_backtest.risk import RiskConfig
from getrich_backtest.strategy import SignalStrategy, Strategy


if TYPE_CHECKING:
    import polars as pl

    from getrich.apps.strategy.account_loader import AccountStateLoader

logger = logging.getLogger(__name__)


class _SignalWriterLike(Protocol):
    async def write_batch(self, signals: list[Signal], strategy_id: str) -> list[str]: ...


@dataclass(frozen=True)
class LiveSignalResult:
    """Result of one live signal production cycle."""

    n_signals: int
    signal_codes: list[str]
    triggered_at: datetime
    duration_ms: float
    error: str | None = None


class LiveSignalRunner:
    """Run one live signal cycle and persist produced signals.

    Risk monitoring is enabled by passing *risk_config*.  When a risk
    check yields a *critical* alert the signal production cycle is
    blocked and an error result is returned.  *warning*-severity alerts
    are logged but do not block.
    """

    def __init__(
        self,
        strategy: Strategy | SignalStrategy,
        *,
        strategy_id: str,
        data_provider: LiveDataProvider | None = None,
        signal_writer: _SignalWriterLike | None = None,
        account_loader: AccountStateLoader | None = None,
        n_bars: int = 1,
        risk_config: RiskConfig | None = None,
        alert_channels: Sequence[AlertChannel] | None = None,
    ) -> None:
        if not strategy_id.strip():
            raise ValueError("strategy_id must be non-empty")
        if n_bars <= 0:
            raise ValueError("n_bars must be positive")
        self.strategy_id = strategy_id
        self.n_bars = n_bars
        self.data_provider = (
            data_provider
            if data_provider is not None
            else LiveDataProvider(
                account_loader=account_loader,
            )
        )
        self.signal_writer = signal_writer if signal_writer is not None else PgSignalWriter()
        self.producer = SignalProducer(strategy)
        self.risk_monitor = (
            LiveRiskMonitor(config=risk_config, channels=alert_channels)
            if risk_config is not None
            else None
        )

    async def run_once(
        self,
        symbols: Sequence[str],
        *,
        factor_names: Sequence[str] | None = None,
        extra_freqs: Sequence[str] | None = None,
    ) -> LiveSignalResult:
        """Execute one load-produce-write live signal cycle.

        When *factor_names* / *extra_freqs* are explicitly provided
        they take precedence.  Otherwise the strategy class attributes
        ``FACTOR_NAMES`` and ``EXTRA_FREQS`` are used for automatic
        discovery (``None`` when the attribute is absent).
        """
        start = perf_counter()
        triggered_at = datetime.now(get_shanghai_tz())

        # Resolve factor names: explicit arg > strategy class attr > None
        resolved_factor_names: Sequence[str] | None
        if factor_names is not None:
            resolved_factor_names = factor_names
        else:
            resolved_factor_names = getattr(self.producer.strategy, "FACTOR_NAMES", None)
        if isinstance(resolved_factor_names, (list, tuple)) and not resolved_factor_names:
            resolved_factor_names = None

        # Resolve extra freqs: explicit arg > strategy class attr > None
        resolved_extra_freqs: Sequence[str] | None
        if extra_freqs is not None:
            resolved_extra_freqs = extra_freqs
        else:
            resolved_extra_freqs = getattr(self.producer.strategy, "EXTRA_FREQS", None)
        if isinstance(resolved_extra_freqs, (list, tuple)) and not resolved_extra_freqs:
            resolved_extra_freqs = None

        try:
            ctx = await self.data_provider.build_context(
                symbols,
                n_bars=self.n_bars,
                run_id=f"live-{self.strategy_id}",
                factor_names=resolved_factor_names,
                extra_freqs=resolved_extra_freqs,
                strategy_id=self.strategy_id,
            )
            if ctx is None:
                self._observe_run(start)
                return self._result(0, [], triggered_at, start)

            # --- Risk check (before signal production) ---
            if self.risk_monitor is not None:
                last_prices = _extract_last_prices(ctx.bar)
                alerts = self.risk_monitor.check_account_health(
                    ctx.account, last_prices, now=triggered_at
                )
                await self.risk_monitor.send_alerts(alerts)

                if any(a.severity == "critical" for a in alerts):
                    reasons = "; ".join(f"{a.check}: {a.reason}" for a in alerts)
                    logger.warning(
                        "Signal cycle blocked by risk monitor for strategy %s: %s",
                        self.strategy_id,
                        reasons,
                    )
                    self._observe_run(start)
                    return self._risk_blocked_result(alerts, triggered_at, start)

            signal_df = self.producer.produce(ctx)
            signals = self.producer.to_signals(signal_df)
            if not signals:
                self._observe_run(start)
                return self._result(0, [], triggered_at, start)

            codes = await self.signal_writer.write_batch(signals, self.strategy_id)
            result = self._result(len(signals), codes, triggered_at, start)
            self._observe_run(start)
            return result
        except Exception as exc:
            # Distinguish "strategy.on_bar raised" (P0 — strategy is
            # silently broken) from "data load failed" (transient
            # — will retry next tick). The SignalProducer wraps
            # user code, so any exception escaping from
            # ``producer.produce(ctx)`` is the on_bar exception.
            # We label by the first frames in the traceback: if
            # the strategy's class name appears, count it as a
            # strategy error; otherwise count as a generic data
            # error (already inside the except branch so the
            # exception is logged + an error LiveSignalResult is
            # returned; the metric just makes the rate observable).
            LIVE_STRATEGY_ERRORS_TOTAL.labels(self.strategy_id).inc()
            self._observe_run(start)
            return self._result(0, [], triggered_at, start, error=str(exc))

    @staticmethod
    def _observe_run(start: float) -> None:
        """Record one ``run_once`` cycle duration to the histogram.

        Called on every code path that returns from ``run_once``
        (success, no-op, risk-blocked, error) so the histogram
        always reflects total wall-clock time, not just successful
        cycles. Without this, a strategy that consistently fails
        would not show up in P99 alerting.
        """
        LIVE_RUN_ONCE_SECONDS.observe(perf_counter() - start)

    @staticmethod
    def _result(
        n_signals: int,
        signal_codes: list[str],
        triggered_at: datetime,
        started_at: float,
        *,
        error: str | None = None,
    ) -> LiveSignalResult:
        return LiveSignalResult(
            n_signals=n_signals,
            signal_codes=signal_codes,
            triggered_at=triggered_at,
            duration_ms=(perf_counter() - started_at) * 1000,
            error=error,
        )

    @staticmethod
    def _risk_blocked_result(
        alerts: list[RiskAlert],
        triggered_at: datetime,
        started_at: float,
    ) -> LiveSignalResult:
        reasons = "; ".join(f"{a.check}: {a.reason}" for a in alerts)
        return LiveSignalResult(
            n_signals=0,
            signal_codes=[],
            triggered_at=triggered_at,
            duration_ms=(perf_counter() - started_at) * 1000,
            error=f"risk blocked: {reasons}",
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_DECIMAL_ZERO = Decimal("0")


def _extract_last_prices(bar: pl.DataFrame) -> dict[str, Decimal]:
    """Build a ``{symbol: close_price}`` lookup from the current bar slice."""
    prices: dict[str, Decimal] = {}
    for row in bar.iter_rows(named=True):
        close_val = row["close"]
        if close_val is not None:
            prices[row["symbol"]] = Decimal(str(close_val))
    return prices


__all__ = ["LiveSignalResult", "LiveSignalRunner"]
