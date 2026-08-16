from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from gr_backtest.exceptions import TimezoneError
from gr_backtest.time import (
    ensure_shanghai_aware,
    get_shanghai_tz,
    normalize_datetime_range,
    require_shanghai_aware,
)


def test_get_shanghai_tz_returns_canonical_timezone() -> None:
    assert get_shanghai_tz().key == "Asia/Shanghai"


def test_require_shanghai_aware_accepts_shanghai_datetime() -> None:
    dt = datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz())
    assert require_shanghai_aware(dt) is dt


def test_require_shanghai_aware_rejects_naive_datetime() -> None:
    with pytest.raises(TimezoneError):
        require_shanghai_aware(datetime(2026, 1, 1, 9, 30))


def test_require_shanghai_aware_rejects_utc_datetime() -> None:
    with pytest.raises(TimezoneError):
        require_shanghai_aware(datetime(2026, 1, 1, 1, 30, tzinfo=timezone.utc))


def test_ensure_shanghai_aware_converts_utc_datetime() -> None:
    dt = datetime(2026, 1, 1, 1, 30, tzinfo=timezone.utc)
    normalized = ensure_shanghai_aware(dt)
    assert normalized.tzinfo == get_shanghai_tz()
    assert normalized.hour == 9


def test_ensure_shanghai_aware_interprets_naive_with_assume_tz() -> None:
    dt = datetime(2026, 1, 1, 1, 30)
    normalized = ensure_shanghai_aware(dt, assume_tz=ZoneInfo("UTC"))
    assert normalized.hour == 9
    assert normalized.tzinfo == get_shanghai_tz()


def test_normalize_datetime_range_rejects_empty_or_reversed_range() -> None:
    start = datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz())
    end = datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz())
    with pytest.raises(TimezoneError):
        normalize_datetime_range(start, end)
