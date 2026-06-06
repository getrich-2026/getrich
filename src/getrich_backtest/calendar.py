"""Trading calendar and session definitions for backtest execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from getrich_backtest.time import require_shanghai_aware


# ---------------------------------------------------------------------------
# Trading session
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Session:
    """A named trading session with explicit time bounds.

    Parameters
    ----------
    name : str
        Display name (e.g. ``"night"``, ``"morning"``, ``"afternoon"``).
    start_hour, start_minute : int
        Session start time (inclusive).
    end_hour, end_minute : int
        Session end time (exclusive).  For midnight-spanning sessions
        (e.g. 21:00-02:30) these refer to the *following* calendar day.
    spans_midnight : bool
        ``True`` when the session crosses midnight.
    """

    name: str
    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int
    spans_midnight: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "start_hour": self.start_hour,
            "start_minute": self.start_minute,
            "end_hour": self.end_hour,
            "end_minute": self.end_minute,
            "spans_midnight": self.spans_midnight,
        }


DEFAULT_FUTURES_SESSIONS: tuple[Session, ...] = (
    Session("night", 21, 0, 2, 30, spans_midnight=True),
    Session("morning", 9, 30, 11, 30, spans_midnight=False),
    Session("afternoon", 13, 0, 15, 0, spans_midnight=False),
)

DEFAULT_ASHARE_SESSIONS: tuple[Session, ...] = (
    Session("morning", 9, 30, 11, 30, spans_midnight=False),
    Session("afternoon", 13, 0, 15, 0, spans_midnight=False),
)


@dataclass(frozen=True)
class Calendar:
    """Simple trading calendar defined by a sorted list of trading days.

    All datetime values must be Asia/Shanghai aware.
    """

    trading_days: tuple[datetime, ...]

    def __post_init__(self) -> None:
        if not self.trading_days:
            raise ValueError("trading_days must be non-empty")
        for dt in self.trading_days:
            require_shanghai_aware(dt)

    def is_trading_day(self, dt: datetime) -> bool:
        """Return True if *dt* falls on a trading day."""
        require_shanghai_aware(dt)
        return dt in self.trading_days

    def is_trading_date(self, d: date) -> bool:
        """Return True if *d* is a trading date (naive date comparison).

        Compares only the date portion, ignoring time-of-day.
        """
        return any(dt.date() == d for dt in self.trading_days)

    def next_trading_day(self, dt: datetime) -> datetime | None:
        """Return the first trading day strictly after *dt*, or None."""
        require_shanghai_aware(dt)
        for td in self.trading_days:
            if td > dt:
                return td
        return None

    def prev_trading_day(self, dt: datetime) -> datetime | None:
        """Return the last trading day strictly before *dt*, or None."""
        require_shanghai_aware(dt)
        prev: datetime | None = None
        for td in self.trading_days:
            if td >= dt:
                break
            prev = td
        return prev

    @staticmethod
    def weekdays_only(
        start: datetime,
        end: datetime,
    ) -> Calendar:
        """Build a calendar of weekdays (Mon–Fri) between *start* and *end*.

        Useful for testing or markets with no exchange holidays.
        """
        require_shanghai_aware(start)
        require_shanghai_aware(end)
        days: list[datetime] = []
        current = start
        while current <= end:
            if current.weekday() < 5:
                days.append(current)
            current += timedelta(days=1)
        return Calendar(trading_days=tuple(days))


__all__ = [
    "Calendar",
    "DEFAULT_ASHARE_SESSIONS",
    "DEFAULT_FUTURES_SESSIONS",
    "Session",
]
