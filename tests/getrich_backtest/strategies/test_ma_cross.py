from datetime import datetime, timedelta
from decimal import Decimal

import polars as pl

from getrich_backtest import Backtest, DataFrameBarLoader
from getrich_backtest.strategies import MACross
from getrich_backtest.time import get_shanghai_tz


def test_ma_cross_buys_when_fast_crosses_above_slow() -> None:
    """Steady state then uptick → fast SMA crosses above slow SMA → BUY."""
    tz = get_shanghai_tz()
    start = datetime(2026, 1, 1, 9, 30, tzinfo=tz)

    # Phase 1: steady at 10 (fast and slow SMA converge to 10)
    steady = [10.0] * 25
    # Phase 2: uptick to 12 (fast SMA rises above slow SMA at transition)
    uptick = [12.0] * 25
    closes = steady + uptick

    df = pl.DataFrame(
        {
            "dt": [start + timedelta(days=i) for i in range(len(closes))],
            "symbol": ["000001.SZ"] * len(closes),
            "open": [c - 0.1 for c in closes],
            "high": [c + 0.2 for c in closes],
            "low": [c - 0.2 for c in closes],
            "close": closes,
            "volume": [1000.0] * len(closes),
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )

    strategy = MACross(fast=5, slow=10)
    bt = Backtest(
        strategy=strategy,
        bar_loader=DataFrameBarLoader(df),
        symbols=["000001.SZ"],
        start=datetime(2026, 1, 1, tzinfo=get_shanghai_tz()),
        end=datetime(2026, 3, 15, tzinfo=get_shanghai_tz()),
        initial_cash=Decimal("10000"),
    )
    result = bt.run()
    buys = [f for f in result.fills if f.side.value in ("BUY", "OPEN_LONG")]
    assert len(buys) >= 1


def test_ma_cross_sells_when_fast_crosses_below_slow() -> None:
    """Steady → uptick (buy) → downtick (sell)."""
    tz = get_shanghai_tz()
    start = datetime(2026, 1, 1, 9, 30, tzinfo=tz)

    # Phase 1: steady at 10 (no crossover — SMAs converge)
    steady = [10.0] * 25
    # Phase 2: uptick to 12 (fast crosses above slow → BUY)
    uptick = [12.0] * 25
    # Phase 3: downtick to 10 (fast crosses below slow → SELL)
    downtick = [10.0] * 25
    closes = steady + uptick + downtick

    df = pl.DataFrame(
        {
            "dt": [start + timedelta(days=i) for i in range(len(closes))],
            "symbol": ["000001.SZ"] * len(closes),
            "open": [c - 0.1 for c in closes],
            "high": [c + 0.2 for c in closes],
            "low": [c - 0.2 for c in closes],
            "close": closes,
            "volume": [1000.0] * len(closes),
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )

    strategy = MACross(fast=5, slow=10)
    bt = Backtest(
        strategy=strategy,
        bar_loader=DataFrameBarLoader(df),
        symbols=["000001.SZ"],
        start=datetime(2026, 1, 1, tzinfo=get_shanghai_tz()),
        end=datetime(2026, 4, 1, tzinfo=get_shanghai_tz()),
        initial_cash=Decimal("10000"),
    )
    result = bt.run()
    sells = [f for f in result.fills if f.side.value in ("SELL", "CLOSE_LONG")]
    assert len(sells) >= 1
