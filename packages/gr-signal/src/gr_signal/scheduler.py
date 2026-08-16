"""Multi-strategy parallel scheduler.

Runs multiple strategies concurrently in a single process using
``asyncio.gather``.  Each strategy is fully isolated — one strategy
crashing does not affect the others.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from gr_backtest import get_shanghai_tz
from gr_backtest.registry import StrategyRegistry, get_registry
from gr_backtest.risk import RiskConfig

from gr_signal.account_loader import AccountStateLoader
from gr_signal.live_risk import AlertChannel
from gr_signal.live_runner import LiveSignalResult, LiveSignalRunner
from gr_signal.signal_writer import PgSignalWriter


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StrategyConfig:
    """Immutable configuration for one strategy in the scheduler.

    Parameters
    ----------
    name : str
        Registered strategy name (e.g. ``"macross"``).
    strategy_id : str
        PostgreSQL UUID of the strategy row.
    symbols : tuple[str, ...]
        Symbols to monitor.
    """

    name: str
    strategy_id: str
    symbols: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("strategy name must be non-empty")
        if not self.strategy_id.strip():
            raise ValueError("strategy_id must be non-empty")
        if not self.symbols:
            raise ValueError("symbols must be non-empty")


@dataclass(frozen=True)
class ScheduleResult:
    """Aggregated result from one scheduler cycle."""

    results: tuple[LiveSignalResult, ...]
    configs: tuple[StrategyConfig, ...]
    triggered_at: datetime
    duration_ms: float

    @property
    def total_signals(self) -> int:
        return sum(r.n_signals for r in self.results)

    @property
    def errors(self) -> list[str]:
        return [r.error for r in self.results if r.error is not None]

    @property
    def all_signal_codes(self) -> list[str]:
        codes: list[str] = []
        for r in self.results:
            codes.extend(r.signal_codes)
        return codes

    def to_dict(self) -> dict:
        return {
            "triggered_at": self.triggered_at.isoformat(),
            "duration_ms": round(self.duration_ms, 2),
            "total_signals": self.total_signals,
            "errors": self.errors,
            "per_strategy": [
                {
                    "name": cfg.name,
                    "strategy_id": cfg.strategy_id,
                    "n_signals": r.n_signals,
                    "signal_codes": r.signal_codes,
                    "duration_ms": round(r.duration_ms, 2),
                    "error": r.error,
                }
                for cfg, r in zip(self.configs, self.results, strict=True)
            ],
        }


class MultiStrategyRunner:
    """Run multiple strategies concurrently.

    Each strategy gets its own ``LiveSignalRunner`` instance.
    Strategies share the global ``pg_pool`` singleton but operate
    on independent data (separate ClickHouse queries, separate
    sub-accounts via ``strategy_id``).

    Parameters
    ----------
    configs : Sequence[StrategyConfig]
        One configuration per strategy to run.
    registry : StrategyRegistry | None
        Strategy registry (default: global singleton).
    risk_config : RiskConfig | None
        Shared risk config applied to every strategy.
    alert_channels : Sequence[AlertChannel] | None
        Shared alert channels applied to every strategy.
    n_bars : int
        Number of recent bars to load per strategy (default 1).
    """

    def __init__(
        self,
        configs: Sequence[StrategyConfig],
        *,
        registry: StrategyRegistry | None = None,
        risk_config: RiskConfig | None = None,
        alert_channels: Sequence[AlertChannel] | None = None,
        n_bars: int = 1,
    ) -> None:
        if not configs:
            raise ValueError("at least one StrategyConfig is required")
        self._configs = tuple(configs)
        self._registry = registry or get_registry()
        self._risk_config = risk_config
        self._alert_channels = alert_channels
        self._n_bars = n_bars

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_all(self) -> ScheduleResult:
        """Run all configured strategies in parallel.

        Each strategy executes independently — failures in one strategy
        do not affect the others.  Results are collected via
        ``asyncio.gather(return_exceptions=True)`` so exceptions from
        malformed strategies are captured as error results rather than
        crashing the scheduler.
        """
        start = _perf_counter()
        triggered_at = datetime.now(get_shanghai_tz())

        coros = [self._run_one(cfg) for cfg in self._configs]
        raw = await asyncio.gather(*coros, return_exceptions=True)

        results: list[LiveSignalResult] = []
        for cfg, r in zip(self._configs, raw, strict=True):
            if isinstance(r, BaseException):
                results.append(
                    LiveSignalResult(
                        n_signals=0,
                        signal_codes=[],
                        triggered_at=triggered_at,
                        duration_ms=0,
                        error=f"{cfg.name}: {r}",
                    )
                )
            else:
                results.append(r)

        return ScheduleResult(
            results=tuple(results),
            configs=self._configs,
            triggered_at=triggered_at,
            duration_ms=(_perf_counter() - start) * 1000,
        )

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    async def _run_one(self, cfg: StrategyConfig) -> LiveSignalResult:
        """Build a runner for *cfg* and execute one cycle."""
        strategy = self._registry.build(cfg.name)
        runner = LiveSignalRunner(
            strategy,
            strategy_id=cfg.strategy_id,
            account_loader=AccountStateLoader(),
            signal_writer=PgSignalWriter(),
            n_bars=self._n_bars,
            risk_config=self._risk_config,
            alert_channels=self._alert_channels,
        )
        return await runner.run_once(list(cfg.symbols))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _perf_counter() -> float:
    from time import perf_counter

    return perf_counter()
