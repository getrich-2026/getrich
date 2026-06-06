"""Timezone utilities for backtests."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from getrich_backtest.exceptions import TimezoneError


_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def get_shanghai_tz() -> ZoneInfo:
    """Return the canonical framework timezone."""
    return _SHANGHAI_TZ


def _is_naive(dt: datetime) -> bool:
    return dt.tzinfo is None or dt.utcoffset() is None


def require_shanghai_aware(dt: datetime) -> datetime:
    """Return dt if it is Asia/Shanghai aware, otherwise raise TimezoneError."""
    if _is_naive(dt):
        raise TimezoneError("datetime must be timezone-aware in Asia/Shanghai")

    if dt.tzinfo != _SHANGHAI_TZ or dt.utcoffset() != _SHANGHAI_TZ.utcoffset(dt):
        raise TimezoneError("datetime timezone must be Asia/Shanghai")

    return dt


def ensure_shanghai_aware(dt: datetime, *, assume_tz: ZoneInfo | None = None) -> datetime:
    """Normalize a datetime to Asia/Shanghai.

    Naive datetimes are explicitly interpreted as ``assume_tz`` when provided,
    otherwise as Asia/Shanghai local time. Aware datetimes are converted.
    """
    if _is_naive(dt):
        return dt.replace(tzinfo=assume_tz or _SHANGHAI_TZ).astimezone(_SHANGHAI_TZ)
    return dt.astimezone(_SHANGHAI_TZ)


def normalize_datetime_range(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    """Normalize a left-closed/right-open datetime range to Asia/Shanghai."""
    normalized_start = ensure_shanghai_aware(start)
    normalized_end = ensure_shanghai_aware(end)
    if normalized_start >= normalized_end:
        raise TimezoneError("start must be earlier than end")
    return normalized_start, normalized_end
