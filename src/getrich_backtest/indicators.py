"""Technical indicators for backtest strategy development.

All indicators are pure functions that accept a Polars DataFrame with
standard OHLCV columns and return a new DataFrame with the indicator
column(s) appended.  Missing values (insufficient history) are filled
with null.
"""

from __future__ import annotations

import polars as pl


def sma(
    df: pl.DataFrame,
    period: int,
    column: str = "close",
) -> pl.DataFrame:
    """Simple moving average."""
    if period < 1:
        raise ValueError("period must be at least 1")
    return df.with_columns(
        pl.col(column)
        .shift(0)
        .rolling_mean(window_size=period)
        .over("symbol")
        .alias(f"sma_{period}")
    )


def ema(
    df: pl.DataFrame,
    period: int,
    column: str = "close",
) -> pl.DataFrame:
    """Exponential moving average."""
    if period < 1:
        raise ValueError("period must be at least 1")
    alpha = 2.0 / (period + 1)
    return df.with_columns(
        pl.col(column).ewm_mean(alpha=alpha, adjust=False).over("symbol").alias(f"ema_{period}")
    )


def rsi(
    df: pl.DataFrame,
    period: int = 14,
    column: str = "close",
) -> pl.DataFrame:
    """Relative Strength Index."""
    if period < 1:
        raise ValueError("period must be at least 1")

    def _rsi(series: pl.Series) -> pl.Series:
        diff = series.diff()
        gain = diff.to_list()
        loss = diff.to_list()
        avg_gain: list[float | None] = []
        avg_loss: list[float | None] = []

        for i in range(len(gain)):
            if i == 0:
                avg_gain.append(None)
                avg_loss.append(None)
                continue
            g = gain[i] if gain[i] is not None and gain[i] > 0 else 0.0
            l_ = -loss[i] if loss[i] is not None and loss[i] < 0 else 0.0
            if i == 1:
                avg_gain.append(g)
                avg_loss.append(l_)
            else:
                prev_g = avg_gain[-1] or 0.0
                prev_l = avg_loss[-1] or 0.0
                avg_gain.append((prev_g * (period - 1) + g) / period)
                avg_loss.append((prev_l * (period - 1) + l_) / period)

        rs: list[float | None] = []
        for ag, al in zip(avg_gain, avg_loss, strict=False):
            if ag is None or al is None:
                rs.append(None)
            elif al == 0.0:
                rs.append(100.0)
            else:
                rs.append(100.0 - 100.0 / (1.0 + ag / al))
        return pl.Series(rs)

    return df.with_columns(_rsi(df[column]).alias(f"rsi_{period}"))


def bollinger(
    df: pl.DataFrame,
    period: int = 20,
    std: int = 2,
    column: str = "close",
) -> pl.DataFrame:
    """Bollinger Bands: mid (SMA), upper, lower."""
    if period < 1:
        raise ValueError("period must be at least 1")
    if std < 1:
        raise ValueError("std must be at least 1")

    mid = pl.col(column).shift(0).rolling_mean(window_size=period).over("symbol")
    stddev = pl.col(column).shift(0).rolling_std(window_size=period).over("symbol")

    return df.with_columns(
        mid.alias("bb_mid"),
        (mid + pl.lit(std) * stddev).alias("bb_upper"),
        (mid - pl.lit(std) * stddev).alias("bb_lower"),
    )


def atr(
    df: pl.DataFrame,
    period: int = 14,
) -> pl.DataFrame:
    """Average True Range."""
    if period < 1:
        raise ValueError("period must be at least 1")

    tr = pl.max_horizontal(
        pl.col("high") - pl.col("low"),
        (pl.col("high") - pl.col("close").shift(1)).abs(),
        (pl.col("low") - pl.col("close").shift(1)).abs(),
    )
    return df.with_columns(
        tr.rolling_mean(window_size=period).over("symbol").alias(f"atr_{period}")
    )
