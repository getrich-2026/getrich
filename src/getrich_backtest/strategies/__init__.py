"""Example strategies built on the getrich_backtest framework."""

from getrich_backtest.strategies.bb_meanrev import BollingerMeanReversion
from getrich_backtest.strategies.ma_cross import MACross


__all__ = [
    "BollingerMeanReversion",
    "MACross",
]
