"""Strategy engine — strategy execution and signal production."""

from gr_backtest.registry import (
    StrategyEntry,
    StrategyRegistry,
    get_registry,
)

from gr_signal.account_loader import AccountStateLoader
from gr_signal.broker import (
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
from gr_signal.errors import (
    BacktestJobError,
    LiveDataError,
    LiveRunnerError,
    SignalWriteError,
    StrategyEngineError,
    StrategyRegistryError,
)
from gr_signal.live_data_provider import LiveDataProvider
from gr_signal.live_risk import (
    AlertChannel,
    EmailAlertChannel,
    LiveRiskMonitor,
    LoggingAlertChannel,
    RiskAlert,
    WebhookAlertChannel,
)
from gr_signal.live_runner import LiveSignalResult, LiveSignalRunner
from gr_signal.scheduler import (
    MultiStrategyRunner,
    ScheduleResult,
    StrategyConfig,
)
from gr_signal.signal_writer import PgSignalWriter
from gr_signal.trade_reconciler import backfill_trade_gaps, reconcile_trades
from gr_signal.trade_writer import BacktestTradeWriter


__all__ = [
    "AccountStateLoader",
    "AlertChannel",
    "BacktestJobError",
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


# 回测作业队列（BacktestJobRunner / BacktestJobOp / 各类 Op）已迁到
# ``gr_api.jobs``：作业由 API 入队、由 Celery worker 执行，属于 gr-api 的领域。
# gr-signal 只管实盘信号生产与交易执行，不再重新导出它们 —— 反向导出会让
# gr_signal 与 gr_api 互相 import，单独安装 gr-signal 直接 ImportError。
