"""COPY 在真实 PostgreSQL 上的事务与重复调用回归。"""

from __future__ import annotations

from datetime import date

import psycopg
import pytest
from gr_data.common.contracts.meta import TRADING_CALENDAR
from gr_data.db.postgres.copy import upsert_rows


pytestmark = pytest.mark.integration


def _row(day: int, is_open: bool) -> tuple:
    return ("XSHG", date(2024, 1, day), is_open, False, None, None)


def test_repeated_upsert_in_one_transaction_and_outer_rollback(pg_conn: psycopg.Connection) -> None:
    assert upsert_rows(pg_conn, TRADING_CALENDAR, [_row(2, True)]) == 1
    assert upsert_rows(pg_conn, TRADING_CALENDAR, [_row(2, False), _row(3, True)]) == 2
    assert pg_conn.execute(
        "SELECT trading_day, is_open FROM meta.trading_calendar ORDER BY trading_day"
    ).fetchall() == [(date(2024, 1, 2), False), (date(2024, 1, 3), True)]
    pg_conn.rollback()
    row = pg_conn.execute("SELECT count(*) FROM meta.trading_calendar").fetchone()
    assert row is not None and row[0] == 0


def test_failed_copy_rolls_back_only_its_savepoint(pg_conn: psycopg.Connection) -> None:
    upsert_rows(pg_conn, TRADING_CALENDAR, [_row(2, True)])
    with pytest.raises(psycopg.errors.NotNullViolation):
        upsert_rows(pg_conn, TRADING_CALENDAR, [("XSHG", None, True, False, None, None)])
    row = pg_conn.execute("SELECT count(*) FROM meta.trading_calendar").fetchone()
    assert row is not None and row[0] == 1
    pg_conn.rollback()


def test_autocommit_copy_commits_once(pg_conn: psycopg.Connection, pg_dsn: dict) -> None:
    pg_conn.commit()
    # conn.info.dsn 不含密码，第二条连接须用原始连接参数建立。
    with psycopg.connect(**pg_dsn, autocommit=True) as conn:
        assert upsert_rows(conn, TRADING_CALENDAR, [_row(4, True)]) == 1
        row = conn.execute("SELECT count(*) FROM meta.trading_calendar").fetchone()
        assert row is not None and row[0] == 1
    row = pg_conn.execute("SELECT count(*) FROM meta.trading_calendar").fetchone()
    assert row is not None and row[0] == 1
    pg_conn.rollback()
