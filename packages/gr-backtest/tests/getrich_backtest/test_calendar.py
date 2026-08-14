from datetime import datetime

import pytest

from getrich_backtest import Calendar, TimezoneError, get_shanghai_tz


def _dt(day: int) -> datetime:
    return datetime(2026, 1, day, 9, 30, tzinfo=get_shanghai_tz())


def _calendar() -> Calendar:
    return Calendar(trading_days=(_dt(2), _dt(3), _dt(5), _dt(6)))  # Fri, Sat, Mon, Tue


def test_is_trading_day_returns_true() -> None:
    cal = _calendar()
    assert cal.is_trading_day(_dt(2))


def test_is_trading_day_returns_false() -> None:
    cal = _calendar()
    assert not cal.is_trading_day(_dt(4))  # Sunday
    assert not cal.is_trading_day(_dt(1))  # Thursday (before Jan 2)


def test_is_trading_date_by_date() -> None:
    cal = _calendar()
    assert cal.is_trading_date(_dt(2).date())
    assert not cal.is_trading_date(_dt(4).date())


def test_next_trading_day() -> None:
    cal = _calendar()
    assert cal.next_trading_day(_dt(2)) == _dt(3)
    assert cal.next_trading_day(_dt(3)) == _dt(5)
    assert cal.next_trading_day(_dt(6)) is None  # last day


def test_prev_trading_day() -> None:
    cal = _calendar()
    assert cal.prev_trading_day(_dt(3)) == _dt(2)
    assert cal.prev_trading_day(_dt(5)) == _dt(3)
    assert cal.prev_trading_day(_dt(2)) is None  # first day


def test_rejects_empty_trading_days() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        Calendar(trading_days=())


def test_rejects_naive_datetime() -> None:
    with pytest.raises((ValueError, TimezoneError)):
        Calendar(trading_days=(datetime(2026, 1, 1),))


def test_is_trading_day_rejects_naive() -> None:
    cal = _calendar()
    with pytest.raises((ValueError, TimezoneError)):
        cal.is_trading_day(datetime(2026, 1, 2))  # type: ignore[arg-type]


def test_weekdays_only_creates_weekday_calendar() -> None:
    start = _dt(1)  # Thursday Jan 1
    end = _dt(7)  # Wednesday Jan 7
    cal = Calendar.weekdays_only(start, end)
    # Jan 1 Thu, Jan 2 Fri, Jan 3 Sat, Jan 4 Sun, Jan 5 Mon, Jan 6 Tue, Jan 7 Wed
    assert cal.is_trading_date(_dt(1).date())  # Thu
    assert cal.is_trading_date(_dt(2).date())  # Fri
    assert not cal.is_trading_date(_dt(3).date())  # Sat
    assert not cal.is_trading_date(_dt(4).date())  # Sun
    assert cal.is_trading_date(_dt(5).date())  # Mon
