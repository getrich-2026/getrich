"""Tests for PgBarLoader.load_calendar() using mocked connections."""

from datetime import date
from unittest.mock import MagicMock

from gr_backtest import PgBarLoader, get_shanghai_tz


TZ = get_shanghai_tz()


def _mock_calendar_rows() -> list[dict]:
    return [
        {"date": date(2026, 6, 1), "is_trading_day": True},
        {"date": date(2026, 6, 2), "is_trading_day": True},
        {"date": date(2026, 6, 3), "is_trading_day": False},
        {"date": date(2026, 6, 4), "is_trading_day": True},
    ]


def _make_mock_conn(rows: list[dict] | None = None) -> MagicMock:
    if rows is None:
        rows = _mock_calendar_rows()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = rows
    mock_cursor.__enter__.return_value = mock_cursor
    mock_cursor.__exit__.return_value = None
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.cursor.return_value.__exit__.return_value = None
    return mock_conn


class TestPgBarLoaderCalendar:
    def test_load_calendar_basic(self) -> None:
        mock_conn = _make_mock_conn()
        loader = PgBarLoader(conn=mock_conn)
        result = loader.load_calendar(exchange="SSE")
        assert result.height == 4
        assert "date" in result.columns
        assert "is_trading_day" in result.columns

    def test_load_calendar_empty(self) -> None:
        mock_conn = _make_mock_conn(rows=[])
        loader = PgBarLoader(conn=mock_conn)
        result = loader.load_calendar(exchange="SSE")
        assert result.is_empty()
        assert result.columns == ["date", "is_trading_day"]

    def test_load_calendar_table_name(self) -> None:
        mock_conn = _make_mock_conn()
        loader = PgBarLoader(conn=mock_conn)
        _ = loader.load_calendar(exchange="SSE")
        call_sql = mock_conn.cursor.return_value.__enter__.return_value.execute.call_args[0][0]
        assert "meta.trading_calendar" in call_sql
        # 交易所改成按列过滤，不再拼进表名
        assert "exchange = %(exchange)s" in call_sql

    def test_load_calendar_custom_exchange(self) -> None:
        """Different exchange → different table name."""
        mock_conn = _make_mock_conn()
        loader = PgBarLoader(conn=mock_conn)
        _ = loader.load_calendar(exchange="SHFE")
        call_sql = mock_conn.cursor.return_value.__enter__.return_value.execute.call_args[0][0]
        assert "meta.trading_calendar" in call_sql
