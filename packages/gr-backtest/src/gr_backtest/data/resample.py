"""Bar resampling utilities for frequency conversion.

All resampling follows standard OHLCV aggregation:

- ``open`` = first open in period
- ``high`` = max high in period
- ``low`` = min low in period
- ``close`` = last close in period
- ``volume`` = sum of volumes in period
- ``amount`` = sum of amounts in period (if present)
- ``vwap`` = amount / volume (if both present)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from gr_backtest.data.schema import validate_bar_schema
from gr_backtest.types import FREQ_TO_MINUTES, Frequency


if TYPE_CHECKING:
    from gr_backtest.calendar import Session


# ---------------------------------------------------------------------------
# Frequency resolution helpers
# ---------------------------------------------------------------------------

_TRUNCATION: dict[str, str] = {
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "60m": "1h",
    "1h": "1h",
    "1d": "1d",
}

_OPTIONAL_CONSTANT_COLS = frozenset({"asset_class", "exchange", "freq"})


def _build_session_bucket_expr(
    target_minutes: int,
    sessions: tuple[Session, ...],
) -> pl.Expr:
    """Build a Polars expression for session-aligned bucket datetimes.

    Each bar is assigned to a bucket whose start time aligns with market
    session boundaries rather than wall-clock boundaries.  Bars outside
    all sessions receive a ``None`` bucket and are filtered out.
    """
    total_minutes = pl.col("dt").dt.hour().cast(pl.Int32) * 60 + pl.col("dt").dt.minute().cast(
        pl.Int32
    )
    date_trunc = pl.col("dt").dt.truncate("1d")

    chain: pl.Expr | None = None

    for sess in sessions:
        sess_start = sess.start_hour * 60 + sess.start_minute
        sess_end = sess.end_hour * 60 + sess.end_minute
        step = target_minutes

        if sess.spans_midnight:
            condition = (total_minutes >= sess_start) | (total_minutes < sess_end)
            adjusted = (
                pl.when(total_minutes >= sess_start)
                .then(total_minutes - sess_start)
                .otherwise(total_minutes + 1440 - sess_start)
            )
            bucket_minutes_expr = sess_start + (adjusted // step) * step

            bucket_dt = (
                pl.when(total_minutes >= sess_start)
                .then(date_trunc + pl.duration(minutes=bucket_minutes_expr))
                .otherwise(
                    date_trunc
                    - pl.duration(days=1)
                    + pl.duration(minutes=bucket_minutes_expr % 1440)
                )
            )
        else:
            condition = (total_minutes >= sess_start) & (total_minutes < sess_end)
            adjusted = total_minutes - sess_start
            bucket_minutes_expr = sess_start + (adjusted // step) * step
            bucket_dt = date_trunc + pl.duration(minutes=bucket_minutes_expr)

        if chain is None:
            chain = pl.when(condition).then(bucket_dt)
        else:
            chain = chain.when(condition).then(bucket_dt)

    if chain is None:
        return pl.lit(None)

    return chain.otherwise(None).alias("_bucket")


def resample_bars(
    bars: pl.DataFrame,
    target_freq: str,
    *,
    source_freq: str = "1m",
    sessions: tuple[Session, ...] | None = None,
) -> pl.DataFrame:
    """Resample finer-frequency bars to a coarser OHLCV frequency.

    Parameters
    ----------
    bars : pl.DataFrame
        Bars at ``source_freq``. Must pass :func:`validate_bar_schema`.
    target_freq : str
        Target frequency. Must be valid per :meth:`Frequency.is_valid`
        and coarser than ``source_freq``.
    source_freq : str
        Source frequency for validation (default ``"1m"``).
    sessions : tuple[Session, ...] | None
        Optional trading session definitions.  When provided, bucket
        boundaries align to session start times (e.g. 09:30, 10:30, …)
        instead of wall-clock truncation (09:00, 10:00, …).  Bars that
        fall outside all sessions are filtered out.

    Returns
    -------
    pl.DataFrame
        Resampled bars at ``target_freq``, sorted by ``(dt, symbol)``.

    Raises
    ------
    ValueError
        If *target_freq* is unknown, not coarser than *source_freq*,
        or not supported for resampling.
    """
    # 1. Validate frequencies -------------------------------------------------
    if not Frequency.is_valid(source_freq):
        raise ValueError(
            f"unknown source_freq '{source_freq}'. Valid: {sorted(Frequency.all_values())}"
        )
    if not Frequency.is_valid(target_freq):
        raise ValueError(
            f"unknown target_freq '{target_freq}'. Valid: {sorted(Frequency.all_values())}"
        )

    source_minutes = FREQ_TO_MINUTES.get(source_freq)
    target_minutes = FREQ_TO_MINUTES.get(target_freq)
    if source_minutes is None or target_minutes is None:
        raise ValueError(
            f"could not resolve minutes for source={source_freq!r} target={target_freq!r}"
        )
    if target_minutes <= source_minutes:
        raise ValueError(
            f"target_freq '{target_freq}' ({target_minutes}m) must be coarser "
            f"than source_freq '{source_freq}' ({source_minutes}m)"
        )
    if target_freq not in _TRUNCATION:
        raise ValueError(f"target_freq '{target_freq}' is not supported for resampling yet")

    # 2. Validate input -------------------------------------------------------
    bars = validate_bar_schema(bars)

    # 3. Compute bucket column -------------------------------------------------
    if sessions is not None:
        bucket_expr = _build_session_bucket_expr(target_minutes, sessions)
        bars_with_bucket = bars.with_columns(bucket_expr)
        # Filter out bars that fall outside all sessions
        bars_with_bucket = bars_with_bucket.filter(pl.col("_bucket").is_not_null())
    else:
        truncation = _TRUNCATION[target_freq]
        bars_with_bucket = bars.with_columns(pl.col("dt").dt.truncate(truncation).alias("_bucket"))

    # 4. Build aggregation expressions ---------------------------------------
    agg_exprs: list[pl.Expr] = [
        pl.col("open").first().alias("open"),
        pl.col("high").max().alias("high"),
        pl.col("low").min().alias("low"),
        pl.col("close").last().alias("close"),
        pl.col("volume").sum().alias("volume"),
    ]

    # Preserve optional amount column
    if "amount" in bars.columns:
        agg_exprs.append(pl.col("amount").sum().alias("amount"))

    # Preserve optional vwap via amount ÷ volume
    has_vwap = "vwap" in bars.columns or "amount" in bars.columns
    if "amount" in bars.columns and "volume" in bars.columns:
        agg_exprs.append((pl.col("amount").sum() / pl.col("volume").sum()).alias("vwap"))
    elif has_vwap and "vwap" in bars.columns:
        # vwap is non-trivial to recompute; forward the last value per bucket
        agg_exprs.append(pl.col("vwap").last().alias("vwap"))

    # Preserve optional columns that are constant per bucket
    for col in _OPTIONAL_CONSTANT_COLS:
        if col in bars.columns:
            agg_exprs.append(pl.col(col).first().alias(col))

    # 5. Aggregate and sort ---------------------------------------------------
    result = (
        bars_with_bucket.group_by(["symbol", "_bucket"], maintain_order=True)
        .agg(agg_exprs)
        .rename({"_bucket": "dt"})
        .sort(["dt", "symbol"])
    )

    return validate_bar_schema(result)


__all__ = ["resample_bars"]
