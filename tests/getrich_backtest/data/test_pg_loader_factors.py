"""Tests for PgBarLoader.load_factors() using mocked connections."""

from datetime import datetime
from unittest.mock import MagicMock

from getrich_backtest import PgBarLoader, get_shanghai_tz


TZ = get_shanghai_tz()


def _mock_factor_rows() -> list[dict]:
    return [
        {
            "dt": datetime(2026, 1, 15, 9, 30, tzinfo=TZ),
            "symbol": "000001.SZ",
            "factor": "mom20",
            "value": 0.05,
        },
        {
            "dt": datetime(2026, 1, 15, 9, 30, tzinfo=TZ),
            "symbol": "000002.SZ",
            "factor": "mom20",
            "value": -0.02,
        },
        {
            "dt": datetime(2026, 1, 15, 9, 30, tzinfo=TZ),
            "symbol": "000001.SZ",
            "factor": "rs_14",
            "value": 0.8,
        },
    ]


def _make_mock_conn(rows: list[dict] | None = None) -> MagicMock:
    if rows is None:
        rows = _mock_factor_rows()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = rows
    mock_cursor.__enter__.return_value = mock_cursor
    mock_cursor.__exit__.return_value = None
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.cursor.return_value.__exit__.return_value = None
    return mock_conn


class TestPgBarLoaderFactors:
    def test_load_factors_basic(self) -> None:
        mock_conn = _make_mock_conn()
        loader = PgBarLoader(conn=mock_conn)
        result = loader.load_factors()
        assert result.height == 3
        assert "dt" in result.columns
        assert "symbol" in result.columns
        assert "factor" in result.columns
        assert "value" in result.columns

    def test_load_factors_empty(self) -> None:
        mock_conn = _make_mock_conn(rows=[])
        loader = PgBarLoader(conn=mock_conn)
        result = loader.load_factors()
        assert result.is_empty()
        assert result.columns == ["dt", "symbol", "factor", "value"]

    def test_load_factors_table_name(self) -> None:
        mock_conn = _make_mock_conn()
        loader = PgBarLoader(conn=mock_conn)
        _ = loader.load_factors()
        call_sql = mock_conn.cursor.return_value.__enter__.return_value.execute.call_args[0][0]
        assert "factors_long" in call_sql

    def test_load_factors_factor_filter(self) -> None:
        mock_conn = _make_mock_conn()
        loader = PgBarLoader(conn=mock_conn)
        _ = loader.load_factors(factors=["mom20"])
        call_sql = mock_conn.cursor.return_value.__enter__.return_value.execute.call_args[0][0]
        assert "ANY" in call_sql or "IN" in call_sql
