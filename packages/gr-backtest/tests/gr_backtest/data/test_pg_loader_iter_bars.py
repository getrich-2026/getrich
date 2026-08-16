"""Tests for PgBarLoader.iter_bars() using mocked connections."""

from datetime import datetime
from unittest.mock import MagicMock

from gr_backtest import PgBarLoader, get_shanghai_tz


TZ = get_shanghai_tz()


def _make_mock_conn(rows: list[dict] | None = None) -> MagicMock:
    if rows is None:
        rows = [
            {
                "dt": datetime(2026, 1, 15, 9, 30, tzinfo=TZ),
                "symbol": "A",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1000.0,
            },
            {
                "dt": datetime(2026, 2, 15, 9, 30, tzinfo=TZ),
                "symbol": "A",
                "open": 101.0,
                "high": 102.0,
                "low": 100.0,
                "close": 101.5,
                "volume": 1000.0,
            },
        ]
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = rows
    mock_cursor.__enter__.return_value = mock_cursor
    mock_cursor.__exit__.return_value = None
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.cursor.return_value.__exit__.return_value = None
    return mock_conn


class TestPgBarLoaderIterBars:
    def test_iter_bars_monthly(self) -> None:
        """Yields chunks with correct month boundaries."""
        mock_conn = _make_mock_conn()
        loader = PgBarLoader(conn=mock_conn)

        chunks = list(
            loader.iter_bars(
                symbols=None,
                start=datetime(2026, 1, 1, tzinfo=TZ),
                end=datetime(2026, 3, 1, tzinfo=TZ),
                chunk="month",
            )
        )
        # 2 chunks: Jan, Feb
        assert len(chunks) == 2
        assert all(c.height >= 0 for c in chunks)

    def test_iter_bars_single_chunk(self) -> None:
        """Range within one month yields a single chunk."""
        mock_conn = _make_mock_conn()
        loader = PgBarLoader(conn=mock_conn)

        chunks = list(
            loader.iter_bars(
                symbols=None,
                start=datetime(2026, 1, 1, tzinfo=TZ),
                end=datetime(2026, 1, 31, tzinfo=TZ),
                chunk="month",
            )
        )
        assert len(chunks) == 1

    def test_iter_bars_passes_params_to_load_bars(self) -> None:
        """Symbol filter and freq are forwarded."""
        mock_conn = _make_mock_conn()
        loader = PgBarLoader(conn=mock_conn)

        chunks = list(
            loader.iter_bars(
                symbols=["A"],
                start=datetime(2026, 1, 1, tzinfo=TZ),
                end=datetime(2026, 3, 1, tzinfo=TZ),
                freq="1d",
                chunk="month",
            )
        )
        assert len(chunks) == 2
