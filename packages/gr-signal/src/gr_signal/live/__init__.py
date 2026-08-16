"""Live signal production module.

Provides the ``Signal`` data model, ``SignalProducer`` for converting
strategy output into signal DataFrames, and the ``SignalWriter`` protocol
with an in-memory ``EvalSignalWriter`` for local evaluation.
"""

from gr_signal.live.errors import LiveSignalError, SignalProductionError
from gr_signal.live.producer import SignalProducer
from gr_signal.live.signal import Signal
from gr_signal.live.writer import EvalSignalWriter, SignalWriter


__all__ = [
    "EvalSignalWriter",
    "LiveSignalError",
    "Signal",
    "SignalProducer",
    "SignalProductionError",
    "SignalWriter",
]
