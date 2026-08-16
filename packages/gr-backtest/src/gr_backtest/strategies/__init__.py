"""Example strategies built on the gr_backtest framework."""

from gr_backtest.strategies.bb_meanrev import BollingerMeanReversion
from gr_backtest.strategies.ma_cross import MACross


__all__ = [
    "BollingerMeanReversion",
    "MACross",
]
