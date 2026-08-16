from datetime import datetime
from zoneinfo import ZoneInfo

import polars as pl
import pytest
from gr_backtest.indicators import atr, bollinger, ema, rsi, sma


def _df(values: list[float]) -> pl.DataFrame:
    """Single-symbol DataFrame with monotonic dates."""
    tz = ZoneInfo("Asia/Shanghai")
    return pl.DataFrame(
        {
            "dt": [datetime(2026, 1, i + 1, 9, 30, tzinfo=tz) for i in range(len(values))],
            "symbol": ["A"] * len(values),
            "open": [float(v) for v in values],
            "high": [float(v) * 1.02 for v in values],
            "low": [float(v) * 0.98 for v in values],
            "close": [float(v) for v in values],
            "volume": [1000.0] * len(values),
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


def test_sma_returns_correct_values() -> None:
    df = _df([1.0, 2.0, 3.0, 4.0, 5.0])
    result = sma(df, period=3)
    col = result["sma_3"].to_list()
    # period=3: first 2 are null, then (1+2+3)/3=2, (2+3+4)/3=3, (3+4+5)/3=4
    assert col[:2] == [None, None]
    assert col[2:] == [2.0, 3.0, 4.0]


def test_sma_rejects_zero_period() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        sma(_df([1.0, 2.0]), period=0)


def test_ema_weights_recent_values_more() -> None:
    df = _df([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    result = ema(df, period=3)
    vals = result["ema_3"].drop_nulls()
    # EMA should be closer to recent values than SMA
    sma_vals = sma(df, period=3)["sma_3"].drop_nulls()
    assert abs(vals[-1] - 10.0) < abs(sma_vals[-1] - 10.0)


def test_rsi_on_uptrend_above_50() -> None:
    df = _df([10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0])
    result = rsi(df, period=5)
    vals = result["rsi_5"].drop_nulls()
    assert all(v is not None and v > 50 for v in vals)


def test_rsi_on_downtrend_below_50() -> None:
    df = _df([20.0, 19.0, 18.0, 17.0, 16.0, 15.0, 14.0, 13.0, 12.0, 11.0, 10.0])
    result = rsi(df, period=5)
    vals = result["rsi_5"].drop_nulls()
    assert all(v is not None and v < 50 for v in vals)


def test_bollinger_bands_ordered_correctly() -> None:
    df = _df([float(i) for i in range(1, 31)])
    result = bollinger(df, period=5)
    result = result.drop_nulls()
    assert (result["bb_upper"] >= result["bb_mid"]).all()
    assert (result["bb_mid"] >= result["bb_lower"]).all()


def test_atr_positive() -> None:
    df = _df([float(i) for i in range(1, 21)])
    result = atr(df, period=5)
    vals = result["atr_5"].drop_nulls()
    assert all(v is not None and v > 0 for v in vals)


def test_indicators_pad_nulls_for_insufficient_history() -> None:
    df = _df([1.0, 2.0])
    result = sma(df, period=5)
    assert result["sma_5"].is_null().all()


def test_indicators_respect_symbol_groups() -> None:
    tz = ZoneInfo("Asia/Shanghai")
    df = pl.DataFrame(
        {
            "dt": [
                datetime(2026, 1, 1, 9, 30, tzinfo=tz),
                datetime(2026, 1, 2, 9, 30, tzinfo=tz),
                datetime(2026, 1, 3, 9, 30, tzinfo=tz),
                datetime(2026, 1, 1, 9, 30, tzinfo=tz),
                datetime(2026, 1, 2, 9, 30, tzinfo=tz),
                datetime(2026, 1, 3, 9, 30, tzinfo=tz),
            ],
            "symbol": ["A", "A", "A", "B", "B", "B"],
            "close": [1.0, 2.0, 3.0, 10.0, 20.0, 30.0],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )
    result = sma(df, period=2)
    # Symbol A: SMA(2) = null, 1.5, 2.5
    # Symbol B: SMA(2) = null, 15.0, 25.0
    a_vals = result.filter(pl.col("symbol") == "A")["sma_2"]
    b_vals = result.filter(pl.col("symbol") == "B")["sma_2"]
    assert a_vals.to_list() == [None, 1.5, 2.5]
    assert b_vals.to_list() == [None, 15.0, 25.0]
