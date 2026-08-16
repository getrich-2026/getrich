from datetime import datetime, timedelta
from decimal import Decimal

import polars as pl
from gr_backtest import Backtest, DataFrameBarLoader
from gr_backtest.strategies import BollingerMeanReversion
from gr_backtest.time import get_shanghai_tz


def _bar_generator(
    n: int,
    close_start: float,
    close_end: float,
    noise: float = 0.0,
) -> pl.DataFrame:
    """Generate a sequence of bars trending from start to end with optional noise."""
    tz = get_shanghai_tz()
    start = datetime(2026, 1, 1, 9, 30, tzinfo=tz)
    closes = []
    for i in range(n):
        t = i / (n - 1) if n > 1 else 0
        price = close_start + (close_end - close_start) * t
        closes.append(price)

    return pl.DataFrame(
        {
            "dt": [start + timedelta(days=i) for i in range(n)],
            "symbol": ["000001.SZ"] * n,
            "open": [c - 0.1 for c in closes],
            "high": [c + 0.2 for c in closes],
            "low": [c - 0.2 for c in closes],
            "close": closes,
            "volume": [1000.0] * n,
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


def test_bb_meanrev_buys_when_close_below_lower_band() -> None:
    """Price drops sharply below the lower band → should produce a BUY signal."""
    # Generate data: starts flat, then sharp drop near the end
    tz = get_shanghai_tz()
    start = datetime(2026, 1, 1, 9, 30, tzinfo=tz)

    # First 40 bars stable around 100, last 10 bars crash to 60
    closes = [100.0 + (i % 5 - 2) * 0.5 for i in range(40)] + [95.0 - 3.5 * i for i in range(10)]

    df = pl.DataFrame(
        {
            "dt": [start + timedelta(days=i) for i in range(len(closes))],
            "symbol": ["000001.SZ"] * len(closes),
            "open": [c - 0.1 for c in closes],
            "high": [c + 0.3 for c in closes],
            "low": [c - 0.3 for c in closes],
            "close": closes,
            "volume": [1000.0] * len(closes),
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )

    strategy = BollingerMeanReversion(period=10, std=2)
    bt = Backtest(
        strategy=strategy,
        bar_loader=DataFrameBarLoader(df),
        symbols=["000001.SZ"],
        start=datetime(2026, 1, 1, tzinfo=get_shanghai_tz()),
        end=datetime(2026, 3, 5, tzinfo=get_shanghai_tz()),
        initial_cash=Decimal("10000"),
    )
    result = bt.run()
    # The sharp drop should trigger at least one BUY
    buys = [f for f in result.fills if f.side.value in ("BUY", "OPEN_LONG")]
    assert len(buys) >= 1


def test_bb_meanrev_sells_when_close_above_upper_band() -> None:
    """Drop below lower band (buy), flat (tighten bands), then sharp spike (sell)."""
    tz = get_shanghai_tz()
    start = datetime(2026, 1, 1, 9, 30, tzinfo=tz)

    # Phase 1: 40 bars steady around 100
    steady = [100.0 + (i % 5 - 2) * 0.5 for i in range(40)]
    # Phase 2: crash from 100 → 60 over 10 bars
    crash = [100.0 - 4.0 * i for i in range(10)]
    # Phase 3: flat around 60 for 15 bars (tightens bands)
    flat = [60.0 + (i % 3 - 1) * 0.5 for i in range(15)]
    # Phase 4: sharp spike 60 → 105 in 5 bars
    spike = [62.0 + 9.0 * i for i in range(5)]

    closes = steady + crash + flat + spike

    df = pl.DataFrame(
        {
            "dt": [start + timedelta(days=i) for i in range(len(closes))],
            "symbol": ["000001.SZ"] * len(closes),
            "open": [c - 0.1 for c in closes],
            "high": [c + 0.3 for c in closes],
            "low": [c - 0.3 for c in closes],
            "close": closes,
            "volume": [1000.0] * len(closes),
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )

    strategy = BollingerMeanReversion(period=10, std=2)
    bt = Backtest(
        strategy=strategy,
        bar_loader=DataFrameBarLoader(df),
        symbols=["000001.SZ"],
        start=datetime(2026, 1, 1, tzinfo=get_shanghai_tz()),
        end=datetime(2026, 4, 1, tzinfo=get_shanghai_tz()),
        initial_cash=Decimal("10000"),
    )
    result = bt.run()
    # Should have at least one BUY (crash) and one SELL (spike overshoots tightened bands)
    sells = [f for f in result.fills if f.side.value in ("SELL", "CLOSE_LONG")]
    assert len(sells) >= 1
