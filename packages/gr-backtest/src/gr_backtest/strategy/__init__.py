"""Strategy-facing APIs."""

from gr_backtest.strategy.alloc_weight import InverseVol, RiskParity, ScoreWeight
from gr_backtest.strategy.allocator import FixedAllocator
from gr_backtest.strategy.base import Strategy
from gr_backtest.strategy.context import (
    AccountView,
    BarContext,
    Context,
    HistoryView,
    PositionView,
    set_ctx_calendar,
    set_ctx_corp_actions,
    set_ctx_factors,
    set_ctx_instruments,
)
from gr_backtest.strategy.order import OrderIntent, TakeProfitStopLoss
from gr_backtest.strategy.portfolio import (
    Constraints,
    EqualWeight,
    PeriodicRebalance,
    Portfolio,
    WeightAllocator,
)
from gr_backtest.strategy.preprocessor import (
    MissingValue,
    Neutralize,
    PreprocessingError,
    SignalPreprocessor,
    Standardize,
    Winsorize,
)
from gr_backtest.strategy.signal import SignalStrategy
from gr_backtest.strategy.target_position import TargetPositionStrategy


__all__ = [
    "AccountView",
    "BarContext",
    "Constraints",
    "Context",
    "EqualWeight",
    "FixedAllocator",
    "HistoryView",
    "InverseVol",
    "MissingValue",
    "Neutralize",
    "OrderIntent",
    "PeriodicRebalance",
    "Portfolio",
    "PositionView",
    "PreprocessingError",
    "RiskParity",
    "ScoreWeight",
    "set_ctx_calendar",
    "set_ctx_corp_actions",
    "set_ctx_factors",
    "set_ctx_instruments",
    "SignalPreprocessor",
    "SignalStrategy",
    "Standardize",
    "Strategy",
    "TakeProfitStopLoss",
    "TargetPositionStrategy",
    "WeightAllocator",
    "Winsorize",
]
