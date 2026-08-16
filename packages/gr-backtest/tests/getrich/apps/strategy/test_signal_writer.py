"""Tests for PgSignalWriter using mocked async connection."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from getrich.apps.strategy import PgSignalWriter, SignalWriteError
from getrich.apps.strategy.signal_writer import _to_params
from gr_data.db.pool import PgConnectionPool
from getrich_backtest import get_shanghai_tz
from getrich_backtest.live import Signal


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_TZ = get_shanghai_tz()
_NOW = datetime(2026, 6, 1, 9, 30, tzinfo=_TZ)
_NOW2 = datetime(2026, 6, 1, 9, 35, tzinfo=_TZ)  # different bar for non-duplicates


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _AsyncCursor:
    """Mock async cursor that tracks executed SQL and simulates RETURNING."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, dict]] = []
        self.fetchone_results: list[tuple | None] = []

    async def __aenter__(self) -> _AsyncCursor:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def execute(self, sql: str, params: dict | None = None) -> None:
        self.executed.append((sql, params or {}))

    async def fetchone(self) -> tuple | None:
        if self.fetchone_results:
            return self.fetchone_results.pop(0)
        # Default behaviour: return signal_code from last executed params
        if self.executed:
            _, params = self.executed[-1]
            code = params.get("code")
            if code:
                return (code,)
        return None


class _AsyncConn:
    """Mock async connection with a controllable cursor."""

    def __init__(self) -> None:
        self.cursor_obj = _AsyncCursor()
        self.committed = False
        self.rolled_back = False

    def cursor(self) -> _AsyncCursor:
        return self.cursor_obj

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class _AsyncCtxMgr:
    """Async context manager that wraps an _AsyncConn."""

    def __init__(self, conn: _AsyncConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _AsyncConn:
        return self._conn

    async def __aexit__(self, *args: object) -> None:
        pass


@pytest.fixture
def mock_pool() -> MagicMock:
    """Create a mock PgConnectionPool with a pre-wired _AsyncConn."""
    pool = MagicMock(spec=PgConnectionPool)
    pool.connection = MagicMock()
    return pool


@pytest.fixture
def async_conn() -> _AsyncConn:
    """Create a fresh mock async connection."""
    return _AsyncConn()


@pytest.fixture
def sample_signal() -> Signal:
    """A minimal Signal instance for testing."""
    return Signal(
        symbol="IF2409",
        action="buy",
        signal_type="entry",
        direction="long",
        trigger_time=_NOW,
    )


@pytest.fixture
def sample_signals() -> list[Signal]:
    """Multiple signals for batch testing."""
    return [
        Signal(symbol="A", action="buy", direction="long", confidence=0.8, trigger_time=_NOW),
        Signal(symbol="B", action="sell", direction="short", confidence=0.6, trigger_time=_NOW),
    ]


@pytest.fixture
def strategy_id() -> str:
    return "550e8400-e29b-41d4-a716-446655440000"


# ---------------------------------------------------------------------------
# Tests — existing behaviour (updated for ON CONFLICT RETURNING)
# ---------------------------------------------------------------------------


class TestPgSignalWriter:
    def test_write_one_success(
        self, mock_pool: MagicMock, async_conn: _AsyncConn, strategy_id: str
    ) -> None:
        """write_one returns a signal_code and executes SQL."""
        mock_pool.connection.return_value = _AsyncCtxMgr(async_conn)
        writer = PgSignalWriter(pool=mock_pool)

        signal = Signal(symbol="IF2409", action="buy", trigger_time=_NOW)
        code = _run(writer.write_one(signal, strategy_id))

        assert code is not None
        assert code.startswith("SIG_")
        assert len(code) > 10
        assert async_conn.committed is True
        assert len(async_conn.cursor_obj.executed) == 1

        sql, params = async_conn.cursor_obj.executed[0]
        assert "INSERT INTO signals" in sql
        assert "ON CONFLICT" in sql
        assert "RETURNING signal_code" in sql
        assert params["symbol"] == "IF2409"
        assert params["action"] == "buy"
        assert params["strategy_id"] == strategy_id

    def test_write_one_with_explicit_conn(
        self, mock_pool: MagicMock, async_conn: _AsyncConn, strategy_id: str
    ) -> None:
        """write_one accepts an explicit connection (no pool acquire)."""
        writer = PgSignalWriter(pool=mock_pool)
        signal = Signal(symbol="A", action="buy", trigger_time=_NOW)

        code = _run(writer.write_one(signal, strategy_id, conn=async_conn))

        assert code is not None
        assert code.startswith("SIG_")
        # No pool connection acquired
        mock_pool.connection.assert_not_called()
        # No commit by the writer (caller manages transaction)
        assert async_conn.committed is False
        assert len(async_conn.cursor_obj.executed) == 1

    def test_write_batch_success(
        self,
        mock_pool: MagicMock,
        async_conn: _AsyncConn,
        sample_signals: list[Signal],
        strategy_id: str,
    ) -> None:
        """write_batch writes all signals and commits once."""
        mock_pool.connection.return_value = _AsyncCtxMgr(async_conn)
        writer = PgSignalWriter(pool=mock_pool)

        codes = _run(writer.write_batch(sample_signals, strategy_id))

        assert len(codes) == 2
        assert all(c.startswith("SIG_") for c in codes)
        assert async_conn.committed is True
        assert len(async_conn.cursor_obj.executed) == 2

    def test_write_batch_empty(self, mock_pool: MagicMock, strategy_id: str) -> None:
        """write_batch with empty list returns empty list."""
        writer = PgSignalWriter(pool=mock_pool)
        codes = _run(writer.write_batch([], strategy_id))
        assert codes == []
        mock_pool.connection.assert_not_called()

    def test_signal_mapping(
        self, mock_pool: MagicMock, async_conn: _AsyncConn, strategy_id: str
    ) -> None:
        """All Signal fields are correctly mapped to SQL params."""
        mock_pool.connection.return_value = _AsyncCtxMgr(async_conn)
        writer = PgSignalWriter(pool=mock_pool)

        from decimal import Decimal

        now = datetime(2026, 6, 1, 9, 30, tzinfo=_TZ)

        signal = Signal(
            symbol="IF2409",
            action="buy",
            signal_type="entry",
            direction="long",
            symbol_name="沪深300",
            exchange="CFFEX",
            trigger_price=Decimal("3500.50"),
            target_price=Decimal("3600.00"),
            stop_loss_price=Decimal("3400.00"),
            suggested_quantity=2,
            position_pct=Decimal("0.15"),
            confidence=Decimal("0.85"),
            urgency="high",
            reason="均线金叉",
            trigger_time=now,
            status="active",
        )

        _run(writer.write_one(signal, strategy_id))
        _, params = async_conn.cursor_obj.executed[0]

        assert params["symbol"] == "IF2409"
        assert params["action"] == "buy"
        assert params["type"] == "entry"
        assert params["direction"] == "long"
        assert params["symbol_name"] == "沪深300"
        assert params["exchange"] == "CFFEX"
        assert params["trigger_price"] == pytest.approx(3500.50)
        assert params["target_price"] == pytest.approx(3600.00)
        assert params["stop_loss_price"] == pytest.approx(3400.00)
        assert params["suggested_qty"] == 2
        assert params["position_pct"] == pytest.approx(0.15)
        assert params["confidence"] == pytest.approx(0.85)
        assert params["urgency"] == "high"
        assert params["reason"] == "均线金叉"
        assert params["status"] == "active"

    def test_database_error_propagates(
        self, mock_pool: MagicMock, async_conn: _AsyncConn, strategy_id: str
    ) -> None:
        """Database errors are wrapped in SignalWriteError."""
        # Make cursor.execute raise
        async_conn.cursor_obj.execute = AsyncMock(side_effect=Exception("connection lost"))  # type: ignore[method-assign]
        mock_pool.connection.return_value = _AsyncCtxMgr(async_conn)
        writer = PgSignalWriter(pool=mock_pool)

        with pytest.raises(SignalWriteError, match="failed to write signal"):
            _run(writer.write_one(Signal(symbol="A", action="buy", trigger_time=_NOW), strategy_id))

    def test_custom_pool(self) -> None:
        """PgSignalWriter accepts a custom pool instance."""
        pool = MagicMock(spec=PgConnectionPool)
        writer = PgSignalWriter(pool=pool)
        assert writer._pool is pool

    def test_default_pool(self) -> None:
        """Default constructor uses the global pg_pool."""
        from getrich.apps.strategy.signal_writer import pg_pool as default_pool

        writer = PgSignalWriter()
        assert writer._pool is default_pool


# ---------------------------------------------------------------------------
# Tests — idempotency (Sub-Task 2)
# ---------------------------------------------------------------------------


class TestSignalIdempotency:
    """Tests for ON CONFLICT DO NOTHING behaviour."""

    def test_write_one_duplicate_returns_none(
        self, mock_pool: MagicMock, async_conn: _AsyncConn, strategy_id: str
    ) -> None:
        """When a duplicate is inserted, write_one returns None."""
        # Simulate ON CONFLICT DO NOTHING: no row returned
        async_conn.cursor_obj.fetchone_results = [None]
        mock_pool.connection.return_value = _AsyncCtxMgr(async_conn)
        writer = PgSignalWriter(pool=mock_pool)

        signal = Signal(symbol="IF2409", action="buy", trigger_time=_NOW)
        code = _run(writer.write_one(signal, strategy_id))

        assert code is None
        assert async_conn.committed is True
        assert len(async_conn.cursor_obj.executed) == 1

    def test_write_batch_all_duplicates_returns_empty(
        self, mock_pool: MagicMock, async_conn: _AsyncConn, strategy_id: str
    ) -> None:
        """When all signals are duplicates, write_batch returns empty list."""
        async_conn.cursor_obj.fetchone_results = [None, None]
        mock_pool.connection.return_value = _AsyncCtxMgr(async_conn)
        writer = PgSignalWriter(pool=mock_pool)

        signals = [
            Signal(symbol="A", action="buy", trigger_time=_NOW),
            Signal(symbol="B", action="sell", trigger_time=_NOW),
        ]
        codes = _run(writer.write_batch(signals, strategy_id))

        assert codes == []
        assert async_conn.committed is True
        assert len(async_conn.cursor_obj.executed) == 2

    def test_write_batch_mixed_new_and_duplicate(
        self, mock_pool: MagicMock, async_conn: _AsyncConn, strategy_id: str
    ) -> None:
        """Mixed batch: first signal is new, second is duplicate."""
        async_conn.cursor_obj.fetchone_results = [
            ("SIG_DUMMY_NEW",),  # first signal: newly inserted
            None,  # second signal: duplicate
        ]
        mock_pool.connection.return_value = _AsyncCtxMgr(async_conn)
        writer = PgSignalWriter(pool=mock_pool)

        signals = [
            Signal(symbol="A", action="buy", trigger_time=_NOW),
            Signal(symbol="A", action="sell", trigger_time=_NOW),
        ]
        codes = _run(writer.write_batch(signals, strategy_id))

        assert codes == ["SIG_DUMMY_NEW"]
        assert len(async_conn.cursor_obj.executed) == 2

    def test_different_trigger_time_both_inserted(
        self, mock_pool: MagicMock, async_conn: _AsyncConn, strategy_id: str
    ) -> None:
        """Two signals with different trigger_time are both inserted."""
        # Default fetchone returns code from params — both succeed
        mock_pool.connection.return_value = _AsyncCtxMgr(async_conn)
        writer = PgSignalWriter(pool=mock_pool)

        signals = [
            Signal(symbol="A", action="buy", trigger_time=datetime(2026, 6, 1, 9, 30, tzinfo=_TZ)),
            Signal(symbol="A", action="buy", trigger_time=datetime(2026, 6, 1, 9, 35, tzinfo=_TZ)),
        ]
        codes = _run(writer.write_batch(signals, strategy_id))

        assert len(codes) == 2

    def test_missing_trigger_time_raises_signal_write_error(
        self,
        strategy_id: str,
    ) -> None:
        """Signal with trigger_time=None raises SignalWriteError from _to_params."""
        signal = Signal(symbol="A", action="buy")  # no trigger_time
        with pytest.raises(SignalWriteError, match="trigger_time must not be None"):
            _to_params(signal, strategy_id, "id-1", "SIG_TEST")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro: object) -> object:
    """Run an async coroutine synchronously for test convenience."""
    import asyncio

    return asyncio.new_event_loop().run_until_complete(coro)  # type: ignore[arg-type]
