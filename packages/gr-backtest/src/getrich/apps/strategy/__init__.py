"""Strategy engine — strategy execution and signal production."""

from getrich.apps.strategy.account_loader import AccountStateLoader
from getrich.apps.strategy.backtest_job_runner import (
    BacktestJobOp,
    BacktestJobRunner,
    BacktestJobRunResult,
    BacktestOneShotOp,
)
from getrich.apps.strategy.broker import (
    BrokerAdapter,
    BrokerError,
    BrokerKind,
    CtpAdapter,
    InMemoryAdapter,
    OrderAck,
    OrderIntent,
    OrderSide,
    OrderStatus,
    TimeInForce,
    XtpAdapter,
)
from getrich.apps.strategy.errors import (
    BacktestJobError,
    LiveDataError,
    LiveRunnerError,
    SignalWriteError,
    StrategyEngineError,
    StrategyRegistryError,
)
from getrich.apps.strategy.live_data_provider import LiveDataProvider
from getrich.apps.strategy.live_risk import (
    AlertChannel,
    EmailAlertChannel,
    LiveRiskMonitor,
    LoggingAlertChannel,
    RiskAlert,
    WebhookAlertChannel,
)
from getrich.apps.strategy.live_runner import LiveSignalResult, LiveSignalRunner
from getrich.apps.strategy.registry import (
    StrategyEntry,
    StrategyRegistry,
    get_registry,
)
from getrich.apps.strategy.scheduler import (
    MultiStrategyRunner,
    ScheduleResult,
    StrategyConfig,
)
from getrich.apps.strategy.signal_writer import PgSignalWriter
from getrich.apps.strategy.trade_reconciler import backfill_trade_gaps, reconcile_trades
from getrich.apps.strategy.trade_writer import BacktestTradeWriter


__all__ = [
    "AccountStateLoader",
    "AlertChannel",
    "BacktestJobError",
    "BacktestJobOp",
    "BacktestJobRunResult",
    "BacktestJobRunner",
    "BacktestOneShotOp",
    "BacktestTradeWriter",
    "EmailAlertChannel",
    "LiveDataError",
    "LiveDataProvider",
    "LiveRiskMonitor",
    "LiveRunnerError",
    "LiveSignalResult",
    "LiveSignalRunner",
    "LoggingAlertChannel",
    "MultiStrategyRunner",
    "PgSignalWriter",
    "RiskAlert",
    "ScheduleResult",
    "SignalWriteError",
    "StrategyConfig",
    "StrategyEngineError",
    "StrategyEntry",
    "StrategyRegistry",
    "StrategyRegistryError",
    "WebhookAlertChannel",
    # Round #1163 — broker integration stubs
    "BrokerAdapter",
    "BrokerError",
    "BrokerKind",
    "CtpAdapter",
    "InMemoryAdapter",
    "OrderAck",
    "OrderIntent",
    "OrderSide",
    "OrderStatus",
    "TimeInForce",
    "XtpAdapter",
    "backfill_trade_gaps",
    "get_registry",
    "reconcile_trades",
]


def __getattr__(name: str) -> object:
    """Lazy-export the backtest execution ``Op`` classes.

    Importing ``getrich.apps.strategy.ops`` eagerly from this package would
    trigger a circular dependency: ``getrich_backtest.__init__`` -> ...
    -> ``getrich.apps.strategy.__init__`` -> ``ops`` -> ``getrich_backtest``.
    Importing the modules on demand keeps the eager import graph acyclic.
    """
    if name in {"BacktestRunOp", "SweepRunOp", "WalkForwardRunOp", "get_op_for_job_type"}:
        from getrich.apps.strategy import ops as _ops

        return getattr(_ops, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
