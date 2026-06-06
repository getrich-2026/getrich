"""Tests for PgBarLoader.load_adj_factors() using mocked connections."""

from datetime import date
from unittest.mock import MagicMock

from getrich_backtest import PgBarLoader


def _mock_adj_rows() -> list[dict]:
    return [
        {"symbol": "000001.SZ", "dt": date(2026, 6, 15), "pre_factor": 0.95, "post_factor": 1.05},
        {"symbol": "000002.SZ", "dt": date(2026, 7, 1), "pre_factor": 0.90, "post_factor": 1.10},
    ]


def _make_mock_conn(rows: list[dict] | None = None) -> MagicMock:
    if rows is None:
        rows = _mock_adj_rows()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = rows
    mock_cursor.__enter__.return_value = mock_cursor
    mock_cursor.__exit__.return_value = None
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.cursor.return_value.__exit__.return_value = None
    return mock_conn


class TestPgBarLoaderAdjFactors:
    def test_load_adj_factors_basic(self) -> None:
        mock_conn = _make_mock_conn()
        loader = PgBarLoader(conn=mock_conn)
        result = loader.load_adj_factors()
        assert result.height == 2
        assert "symbol" in result.columns
        assert "dt" in result.columns
        assert "pre_factor" in result.columns
        assert "post_factor" in result.columns

    def test_load_adj_factors_empty(self) -> None:
        mock_conn = _make_mock_conn(rows=[])
        loader = PgBarLoader(conn=mock_conn)
        result = loader.load_adj_factors()
        assert result.is_empty()
        assert result.columns == ["symbol", "dt", "pre_factor", "post_factor"]

    def test_load_adj_factors_table_name(self) -> None:
        mock_conn = _make_mock_conn()
        loader = PgBarLoader(conn=mock_conn)
        _ = loader.load_adj_factors()
        call_sql = mock_conn.cursor.return_value.__enter__.return_value.execute.call_args[0][0]
        assert "md_adj_factor_equity" in call_sql
