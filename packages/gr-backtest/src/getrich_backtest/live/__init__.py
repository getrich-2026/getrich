"""Live signal production module.

Provides the ``Signal`` data model, ``SignalProducer`` for converting
strategy output into signal DataFrames, and the ``SignalWriter`` protocol
with an in-memory ``EvalSignalWriter`` for local evaluation.
"""

from getrich_backtest.live.errors import LiveSignalError, SignalProductionError
from getrich_backtest.live.producer import SignalProducer
from getrich_backtest.live.signal import Signal
from getrich_backtest.live.writer import EvalSignalWriter, SignalWriter


__all__ = [
    "EvalSignalWriter",
    "LiveSignalError",
    "Signal",
    "SignalProducer",
    "SignalProductionError",
    "SignalWriter",
]
