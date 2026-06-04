from __future__ import annotations

from datetime import date
from datetime import datetime
from datetime import time
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.engine import Connection

from getrich_data_import.services import TradingCalendarClosedError
from getrich_data_import.services import TradingCalendarMissingError
from getrich_data_import.services import TradingCalendarService


@pytest.fixture
def conn() -> Connection:
    engine = create_engine("sqlite://", future=True)
    with engine.connect() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS meta")
        connection.exec_driver_sql(
            """
            CREATE TABLE meta.trading_calendar (
                exchange TEXT NOT NULL,
                trading_day DATE NOT NULL,
                is_open BOOLEAN NOT NULL,
                has_night BOOLEAN NOT NULL DEFAULT false,
                prev_trading_day DATE,
                next_trading_day DATE,
                PRIMARY KEY (exchange, trading_day)
            )
            """
        )
        connection.execute(
            text(
                """
                INSERT INTO meta.trading_calendar
                    (exchange, trading_day, is_open, prev_trading_day, next_trading_day)
                VALUES
                    (:exchange, :trading_day, :is_open, :prev_trading_day, :next_trading_day)
                """
            ),
            [
                {
                    "exchange": "XSHG",
                    "trading_day": date(2026, 5, 29),
                    "is_open": True,
                    "prev_trading_day": date(2026, 5, 28),
                    "next_trading_day": date(2026, 6, 1),
                },
                {
                    "exchange": "XSHG",
                    "trading_day": date(2026, 5, 30),
                    "is_open": False,
                    "prev_trading_day": date(2026, 5, 29),
                    "next_trading_day": date(2026, 6, 1),
                },
                {
                    "exchange": "XSHG",
                    "trading_day": date(2026, 5, 31),
                    "is_open": False,
                    "prev_trading_day": date(2026, 5, 29),
                    "next_trading_day": date(2026, 6, 1),
                },
                {
                    "exchange": "XSHG",
                    "trading_day": date(2026, 6, 1),
                    "is_open": True,
                    "prev_trading_day": date(2026, 5, 29),
                    "next_trading_day": date(2026, 6, 2),
                },
                {
                    "exchange": "XSHG",
                    "trading_day": date(2026, 6, 2),
                    "is_open": True,
                    "prev_trading_day": date(2026, 6, 1),
                    "next_trading_day": None,
                },
                {
                    "exchange": "XSHG",
                    "trading_day": date(2026, 5, 28),
                    "is_open": True,
                    "prev_trading_day": None,
                    "next_trading_day": date(2026, 5, 29),
                },
            ],
        )
        yield connection


def test_is_trading_day_requires_calendar_row(conn: Connection) -> None:
    service = TradingCalendarService(conn)

    assert service.is_trading_day("XSHG", date(2026, 5, 29)) is True
    assert service.is_trading_day("XSHG", date(2026, 5, 30)) is False

    with pytest.raises(TradingCalendarMissingError, match="missing row"):
        service.is_trading_day("XSHG", date(2026, 6, 3))


def test_next_and_previous_trading_day_use_calendar_links(conn: Connection) -> None:
    service = TradingCalendarService(conn)

    assert service.next_trading_day("XSHG", date(2026, 5, 31)) == date(2026, 6, 1)
    assert service.prev_trading_day("XSHG", date(2026, 5, 31)) == date(2026, 5, 29)


def test_adjacent_trading_day_falls_back_to_open_calendar_search(conn: Connection) -> None:
    conn.execute(
        text(
            """
            UPDATE meta.trading_calendar
            SET next_trading_day = NULL
            WHERE exchange = :exchange AND trading_day = :trading_day
            """
        ),
        {"exchange": "XSHG", "trading_day": date(2026, 5, 31)},
    )
    service = TradingCalendarService(conn)

    assert service.next_trading_day("XSHG", date(2026, 5, 31)) == date(2026, 6, 1)


def test_assign_trading_day_applies_configurable_night_cutoff(conn: Connection) -> None:
    service = TradingCalendarService(conn)
    tz = ZoneInfo("Asia/Shanghai")

    assert service.assign_trading_day(
        "XSHG",
        datetime(2026, 5, 29, 20, 59, tzinfo=tz),
        time(21, 0),
    ) == date(2026, 5, 29)
    assert service.assign_trading_day(
        "XSHG",
        datetime(2026, 5, 29, 21, 0, tzinfo=tz),
        time(21, 0),
    ) == date(2026, 6, 1)


def test_assign_trading_day_converts_aware_timestamp_to_shanghai(conn: Connection) -> None:
    service = TradingCalendarService(conn)

    assert service.assign_trading_day(
        "XSHG",
        datetime(2026, 5, 29, 13, 0, tzinfo=ZoneInfo("UTC")),
        time(21, 0),
    ) == date(2026, 6, 1)


def test_assign_trading_day_rejects_closed_day_before_cutoff(conn: Connection) -> None:
    service = TradingCalendarService(conn)

    with pytest.raises(TradingCalendarClosedError, match="closed trading day"):
        service.assign_trading_day(
            "XSHG",
            datetime(2026, 5, 30, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
            time(21, 0),
        )


def test_assign_trading_day_missing_weekend_row_has_actionable_message(conn: Connection) -> None:
    conn.execute(
        text(
            """
            DELETE FROM meta.trading_calendar
            WHERE exchange = :exchange AND trading_day = :trading_day
            """
        ),
        {"exchange": "XSHG", "trading_day": date(2026, 5, 30)},
    )
    service = TradingCalendarService(conn)

    with pytest.raises(TradingCalendarMissingError, match="include weekends and holidays"):
        service.assign_trading_day(
            "XSHG",
            datetime(2026, 5, 30, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
            time(21, 0),
        )


def test_assign_trading_day_rejects_naive_timestamp(conn: Connection) -> None:
    service = TradingCalendarService(conn)

    with pytest.raises(ValueError, match="timezone-aware"):
        service.assign_trading_day(
            "XSHG",
            datetime(2026, 5, 29, 21, 0),
            time(21, 0),
        )
