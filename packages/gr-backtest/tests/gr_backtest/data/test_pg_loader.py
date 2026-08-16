"""Tests for PgBarLoader using mocked psycopg connections."""

from datetime import datetime
from unittest.mock import MagicMock

import polars as pl
import pytest
from gr_backtest import (
    DataLoadError,
    PgBarLoader,
    get_shanghai_tz,
)


TZ = get_shanghai_tz()


def _mock_rows() -> list[dict]:
    """Return a small set of mock bar rows as dict_rows would return."""
    return [
        {
            "dt": datetime(2026, 6, 1, 9, 30, tzinfo=TZ),
            "symbol": "A",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1000.0,
        },
        {
            "dt": datetime(2026, 6, 1, 9, 30, tzinfo=TZ),
            "symbol": "B",
            "open": 50.0,
            "high": 51.0,
            "low": 49.0,
            "close": 50.5,
            "volume": 2000.0,
        },
        {
            "dt": datetime(2026, 6, 2, 9, 30, tzinfo=TZ),
            "symbol": "A",
            "open": 101.0,
            "high": 102.0,
            "low": 100.0,
            "close": 101.5,
            "volume": 1100.0,
        },
        {
            "dt": datetime(2026, 6, 2, 9, 30, tzinfo=TZ),
            "symbol": "B",
            "open": 51.0,
            "high": 52.0,
            "low": 50.0,
            "close": 51.5,
            "volume": 2100.0,
        },
    ]


def _make_mock_conn(rows: list[dict] | None = None) -> MagicMock:
    """Create a mock psycopg Connection with cursor returning given rows."""
    if rows is None:
        rows = _mock_rows()

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = rows
    mock_cursor.__enter__.return_value = mock_cursor
    mock_cursor.__exit__.return_value = None
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.cursor.return_value.__exit__.return_value = None

    return mock_conn


# ---------------------------------------------------------------------------
# PgBarLoader tests
# ---------------------------------------------------------------------------


class TestPgBarLoader:
    def test_load_bars_basic(self) -> None:
        """Basic query passes correct SQL and returns validated DataFrame."""
        mock_conn = _make_mock_conn()
        loader = PgBarLoader(conn=mock_conn)
        result = loader.load_bars(
            symbols=["A", "B"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),
        )
        assert result.height == 4
        assert result.columns == ["dt", "symbol", "open", "high", "low", "close", "volume"]
        assert result["dt"].dtype == pl.Datetime("ms", "Asia/Shanghai")

    def test_load_bars_column_projection(self) -> None:
        """columns parameter projects all required columns (optional filtering not tested)."""
        mock_conn = _make_mock_conn()
        loader = PgBarLoader(conn=mock_conn)
        result = loader.load_bars(
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),
            columns=["dt", "symbol", "open", "high", "low", "close", "volume"],
        )
        assert result.columns == ["dt", "symbol", "open", "high", "low", "close", "volume"]

    def test_load_bars_columns_missing_required_raises(self) -> None:
        """columns missing a required column raises DataLoadError."""
        mock_conn = _make_mock_conn()
        loader = PgBarLoader(conn=mock_conn)
        with pytest.raises(DataLoadError, match="required bar columns"):
            loader.load_bars(
                symbols=["A"],
                start=datetime(2026, 6, 1, tzinfo=TZ),
                end=datetime(2026, 6, 3, tzinfo=TZ),
                columns=["dt", "symbol"],  # missing close, volume, etc.
            )

    def test_load_bars_all_symbols(self) -> None:
        """symbols=None does not add symbol filter to query."""
        mock_conn = _make_mock_conn()
        loader = PgBarLoader(conn=mock_conn)
        result = loader.load_bars(
            symbols=None,
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 3, tzinfo=TZ),
        )
        # Should return all rows (no symbol filter)
        assert result.height == 4

    def test_table_name_default(self) -> None:
        """不指定 asset_class 时落到默认品种 stock。

        行情表按品种分表（``market.stock_bar_1d`` 等），没有「所有品种」的合并表，
        所以默认值必须是某个具体品种，不能拼出一个不存在的表名。
        """
        name = PgBarLoader._table_name(None, "1d")
        assert name == "market.stock_bar_1d"

    def test_table_name_with_asset_class(self) -> None:
        """表名用 gr-data 的 market schema 命名：``market.{asset}_bar_{freq}``。"""
        assert PgBarLoader._table_name("stock", "1d") == "market.stock_bar_1d"
        assert PgBarLoader._table_name("index", "1m") == "market.index_bar_1m"
        assert PgBarLoader._table_name("future", "1d") == "market.future_bar_1d"

    def test_load_bars_empty_result(self) -> None:
        """Empty result set returns empty DataFrame with valid schema."""
        mock_conn = _make_mock_conn(rows=[])
        loader = PgBarLoader(conn=mock_conn)
        result = loader.load_bars(
            symbols=["NONEXISTENT"],
            start=datetime(2026, 1, 1, tzinfo=TZ),
            end=datetime(2026, 1, 2, tzinfo=TZ),
        )
        assert result.is_empty()
        assert result.columns == ["dt", "symbol", "open", "high", "low", "close", "volume"]

    def test_load_bars_db_error_raises(self) -> None:
        """Database error is wrapped in DataLoadError."""
        mock_conn = MagicMock()
        mock_conn.cursor.side_effect = RuntimeError("connection lost")
        loader = PgBarLoader(conn=mock_conn)
        with pytest.raises(DataLoadError, match="query failed"):
            loader.load_bars(
                symbols=["A"],
                start=datetime(2026, 6, 1, tzinfo=TZ),
                end=datetime(2026, 6, 2, tzinfo=TZ),
            )

    def test_asset_class_filter_affects_table_name(self) -> None:
        """asset_class 决定查哪张行情表。"""
        mock_conn = _make_mock_conn()
        loader = PgBarLoader(conn=mock_conn)
        _ = loader.load_bars(
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 2, tzinfo=TZ),
            asset_class="index",
        )
        # Verify the SQL was constructed with the right table name
        call_sql = mock_conn.cursor.return_value.__enter__.return_value.execute.call_args[0][0]
        assert "market.index_bar_1d" in call_sql
        # 行情表用 instrument_id 外键，symbol 必须靠 JOIN meta.instruments 拿到
        assert "JOIN meta.instruments" in call_sql

    def test_freq_parameter_affects_table_name(self) -> None:
        """freq parameter changes the query table."""
        mock_conn = _make_mock_conn()
        loader = PgBarLoader(conn=mock_conn)
        _ = loader.load_bars(
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 2, tzinfo=TZ),
            freq="1m",
        )
        call_sql = mock_conn.cursor.return_value.__enter__.return_value.execute.call_args[0][0]
        assert "market.stock_bar_1m" in call_sql


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestPgBarLoaderProtocol:
    def test_is_bar_loader(self) -> None:
        """PgBarLoader satisfies the BarLoader protocol (has load_bars)."""

        # Structural subtyping: PgBarLoader has load_bars method
        loader = PgBarLoader(conn=MagicMock())
        assert hasattr(loader, "load_bars")
        assert callable(loader.load_bars)
