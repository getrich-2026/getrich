from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from datetime import datetime
from datetime import time
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.engine import Connection

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class TradingCalendarError(ValueError):
    """Base exception for trading-calendar lookup failures."""


class TradingCalendarMissingError(TradingCalendarError):
    """Raised when required calendar rows are absent."""


class TradingCalendarClosedError(TradingCalendarError):
    """Raised when an operation would assign data to a closed trading day."""


@dataclass(frozen=True)
class _CalendarRow:
    trading_day: date
    is_open: bool
    prev_trading_day: date | None
    next_trading_day: date | None


class TradingCalendarService:
    """Trading-day resolver backed by meta.trading_calendar."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def is_trading_day(self, exchange: str, day: date) -> bool:
        row = self._calendar_row(exchange, day)
        return row.is_open

    def next_trading_day(self, exchange: str, day: date) -> date:
        exchange = self._normalize_exchange(exchange)
        day = self._coerce_day(day)
        row = self._calendar_row(exchange, day)
        candidate = row.next_trading_day or self._lookup_adjacent_open_day(
            exchange,
            day,
            direction="next",
        )
        if candidate is None:
            raise TradingCalendarMissingError(
                f"meta.trading_calendar has no next trading day for exchange "
                f"{exchange!r} after {day.isoformat()}"
            )
        self._require_open_day(exchange, candidate, relation="next")
        return candidate

    def prev_trading_day(self, exchange: str, day: date) -> date:
        exchange = self._normalize_exchange(exchange)
        day = self._coerce_day(day)
        row = self._calendar_row(exchange, day)
        candidate = row.prev_trading_day or self._lookup_adjacent_open_day(
            exchange,
            day,
            direction="prev",
        )
        if candidate is None:
            raise TradingCalendarMissingError(
                f"meta.trading_calendar has no previous trading day for exchange "
                f"{exchange!r} before {day.isoformat()}"
            )
        self._require_open_day(exchange, candidate, relation="previous")
        return candidate

    def assign_trading_day(
        self,
        exchange: str,
        timestamp: datetime,
        night_session_cutoff: time,
    ) -> date:
        local_ts = self._to_shanghai_timestamp(timestamp)
        cutoff = self._validate_cutoff(night_session_cutoff)
        local_day = local_ts.date()

        if local_ts.time() >= cutoff:
            try:
                return self.next_trading_day(exchange, local_day)
            except TradingCalendarMissingError as exc:
                raise TradingCalendarMissingError(
                    f"cannot assign timestamp {local_ts.isoformat()} because "
                    f"meta.trading_calendar has no row for local day {local_day.isoformat()} "
                    f"on exchange {self._normalize_exchange(exchange)!r}; include weekends and holidays "
                    f"when night-session timestamps may fall on non-trading calendar days"
                ) from exc

        try:
            is_open = self.is_trading_day(exchange, local_day)
        except TradingCalendarMissingError as exc:
            raise TradingCalendarMissingError(
                f"cannot assign timestamp {local_ts.isoformat()} because "
                f"meta.trading_calendar has no row for local day {local_day.isoformat()} "
                f"on exchange {self._normalize_exchange(exchange)!r}; include weekends and holidays "
                f"when timestamps may fall on non-trading calendar days"
            ) from exc

        if not is_open:
            raise TradingCalendarClosedError(
                f"cannot assign timestamp {local_ts.isoformat()} to closed trading day "
                f"{local_day.isoformat()} for exchange {self._normalize_exchange(exchange)!r}"
            )
        return local_day

    def _calendar_row(self, exchange: str, day: date) -> _CalendarRow:
        exchange = self._normalize_exchange(exchange)
        day = self._coerce_day(day)
        row = (
            self._conn.execute(
                text(
                    """
                    SELECT trading_day, is_open, prev_trading_day, next_trading_day
                    FROM meta.trading_calendar
                    WHERE exchange = :exchange AND trading_day = :trading_day
                    """
                ),
                {"exchange": exchange, "trading_day": day},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise TradingCalendarMissingError(
                f"meta.trading_calendar missing row for exchange {exchange!r} "
                f"on {day.isoformat()}"
            )
        return _CalendarRow(
            trading_day=self._coerce_day(row["trading_day"]),
            is_open=bool(row["is_open"]),
            prev_trading_day=self._coerce_optional_day(row["prev_trading_day"]),
            next_trading_day=self._coerce_optional_day(row["next_trading_day"]),
        )

    def _lookup_adjacent_open_day(
        self,
        exchange: str,
        day: date,
        *,
        direction: str,
    ) -> date | None:
        if direction == "next":
            comparator = ">"
            ordering = "ASC"
        elif direction == "prev":
            comparator = "<"
            ordering = "DESC"
        else:
            raise ValueError(f"unsupported calendar direction: {direction}")

        value = self._conn.execute(
            text(
                f"""
                SELECT trading_day
                FROM meta.trading_calendar
                WHERE exchange = :exchange
                  AND is_open = true
                  AND trading_day {comparator} :trading_day
                ORDER BY trading_day {ordering}
                LIMIT 1
                """
            ),
            {"exchange": exchange, "trading_day": day},
        ).scalar_one_or_none()
        return self._coerce_optional_day(value)

    def _require_open_day(self, exchange: str, day: date, *, relation: str) -> None:
        row = self._calendar_row(exchange, day)
        if not row.is_open:
            raise TradingCalendarClosedError(
                f"meta.trading_calendar {relation} trading day pointer for exchange "
                f"{exchange!r} points to closed day {day.isoformat()}"
            )

    @staticmethod
    def _normalize_exchange(exchange: str) -> str:
        normalized = exchange.strip()
        if not normalized:
            raise ValueError("exchange must not be blank")
        return normalized

    @staticmethod
    def _coerce_day(value: object) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            return date.fromisoformat(value[:10])
        raise TypeError(f"expected date-like value, got {type(value).__name__}")

    @classmethod
    def _coerce_optional_day(cls, value: object) -> date | None:
        if value is None:
            return None
        return cls._coerce_day(value)

    @staticmethod
    def _to_shanghai_timestamp(timestamp: datetime) -> datetime:
        if not isinstance(timestamp, datetime):
            raise TypeError(f"timestamp must be datetime, got {type(timestamp).__name__}")
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return timestamp.astimezone(SHANGHAI_TZ)

    @staticmethod
    def _validate_cutoff(value: time) -> time:
        if not isinstance(value, time):
            raise TypeError(f"night_session_cutoff must be time, got {type(value).__name__}")
        if value.tzinfo is not None and value.utcoffset() is not None:
            raise ValueError("night_session_cutoff must be a local time without tzinfo")
        return value
