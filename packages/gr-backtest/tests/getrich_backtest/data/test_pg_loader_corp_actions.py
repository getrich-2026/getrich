"""Tests for PgBarLoader.load_corp_actions() using mocked connections."""

from datetime import date, datetime
from unittest.mock import MagicMock

from getrich_backtest import PgBarLoader, get_shanghai_tz


TZ = get_shanghai_tz()


def _mock_corp_actions_rows() -> list[dict]:
    return [
        {
            "symbol": "000001.SZ",
            "ex_date": date(2026, 6, 15),
            "action_type": "dividend",
            "amount": 0.5,
        },
        {
            "symbol": "000002.SZ",
            "ex_date": date(2026, 7, 1),
            "action_type": "split",
            "split_ratio": 2.0,
        },
    ]


def _make_mock_conn(rows: list[dict] | None = None) -> MagicMock:
    if rows is None:
        rows = _mock_corp_actions_rows()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = rows
    mock_cursor.__enter__.return_value = mock_cursor
    mock_cursor.__exit__.return_value = None
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.cursor.return_value.__exit__.return_value = None
    return mock_conn


class TestPgBarLoaderCorpActions:
    def test_load_corp_actions_basic(self) -> None:
        mock_conn = _make_mock_conn()
        loader = PgBarLoader(conn=mock_conn)
        result = loader.load_corp_actions()
        assert result.height == 2
        assert "symbol" in result.columns
        assert "ex_date" in result.columns
        assert "action_type" in result.columns

    def test_load_corp_actions_empty(self) -> None:
        mock_conn = _make_mock_conn(rows=[])
        loader = PgBarLoader(conn=mock_conn)
        result = loader.load_corp_actions()
        assert result.is_empty()
        assert result.columns == ["symbol", "ex_date", "action_type"]

    def test_load_corp_actions_table_name(self) -> None:
        mock_conn = _make_mock_conn()
        loader = PgBarLoader(conn=mock_conn)
        _ = loader.load_corp_actions()
        call_sql = mock_conn.cursor.return_value.__enter__.return_value.execute.call_args[0][0]
        assert "corp_actions" in call_sql

    def test_load_corp_actions_symbol_filter(self) -> None:
        mock_conn = _make_mock_conn()
        loader = PgBarLoader(conn=mock_conn)
        _ = loader.load_corp_actions(symbols=["000001.SZ"])
        call_sql = mock_conn.cursor.return_value.__enter__.return_value.execute.call_args[0][0]
        assert "ANY" in call_sql or "IN" in call_sql

    def test_load_corp_actions_date_filter(self) -> None:
        mock_conn = _make_mock_conn()
        loader = PgBarLoader(conn=mock_conn)
        _ = loader.load_corp_actions(
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 30, tzinfo=TZ),
        )
        call_kwargs = mock_conn.cursor.return_value.__enter__.return_value.execute.call_args[0][1]
        assert "start" in call_kwargs
        assert "end" in call_kwargs
