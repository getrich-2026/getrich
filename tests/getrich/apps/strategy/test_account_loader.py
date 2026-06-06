"""Tests for AccountStateLoader."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

from getrich.apps.strategy.account_loader import AccountStateLoader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Mock async cursor with configurable results."""

    def __init__(self, fetchone_result=None, fetchall_result=None, exc=None):
        self._fetchone = fetchone_result
        self._fetchall = fetchall_result
        self._exc = exc
        self.executed: list[tuple[str, tuple]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self._exc:
            raise self._exc

    async def fetchone(self):
        return self._fetchone

    async def fetchall(self):
        return self._fetchall or []


class _FakeConn:
    """Mock async connection."""

    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class _FakeConnCtxMgr:
    """Async context manager for _FakeConn."""

    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass


def _cursor_with_cash(
    cash=Decimal("100000"),
    available=Decimal("50000"),
    maintenance_margin=Decimal("0"),
):
    """Return a cursor populated with a cash row."""
    return _FakeCursor(
        fetchone_result={
            "cash": cash,
            "available_cash": available,
            "maintenance_margin": maintenance_margin,
        },
    )


def _cursor_with_positions(positions: list[dict]):
    """Return a cursor populated with position rows."""
    return _FakeCursor(
        fetchall_result=positions,
    )


def _cursor_with_error(exc: Exception):
    """Return a cursor that raises on execute."""
    return _FakeCursor(exc=exc)


class _FakePool:
    """Minimal pool fake whose ``connection()`` cycles through connections."""

    def __init__(self, conns: list[_FakeConn]) -> None:
        self._conns = conns
        self._idx = 0

    def connection(self) -> _FakeConnCtxMgr:
        conn = self._conns[self._idx]
        self._idx += 1
        return _FakeConnCtxMgr(conn)


def _run(coro):
    import asyncio

    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAccountStateLoader:
    def test_load_account_view_with_cash_and_positions(self):
        """Full account state with cash and two positions."""
        cash_cursor = _cursor_with_cash(Decimal("100000"), Decimal("80000"))
        pos_cursor = _cursor_with_positions(
            [
                {"symbol": "A", "qty": Decimal("100")},
                {"symbol": "B", "qty": Decimal("200")},
            ]
        )
        pool = _FakePool([_FakeConn(cash_cursor), _FakeConn(pos_cursor)])

        loader = AccountStateLoader(pool=pool)
        view = _run(loader.load_account_view())

        assert view.cash == Decimal("100000")
        assert view.available_cash == Decimal("80000")
        assert view.position("A").qty == Decimal("100")
        assert view.position("B").qty == Decimal("200")
        # Unknown symbol returns zero-qty PositionView
        assert view.position("C").qty == Decimal("0")

    def test_load_account_view_empty_db_returns_zero_state(self):
        """When no cash row exists, returns zero-state AccountView."""
        cash_cursor = _FakeCursor(fetchone_result=None)  # no row
        pos_cursor = _cursor_with_positions([])
        pool = _FakePool([_FakeConn(cash_cursor), _FakeConn(pos_cursor)])

        loader = AccountStateLoader(pool=pool)
        view = _run(loader.load_account_view())

        assert view.cash == Decimal("0")
        assert view.available_cash == Decimal("0")
        assert view.positions == {} or len(view.positions) == 0  # type: ignore[arg-type]

    def test_zero_qty_positions_filtered(self):
        """Positions with qty=0 are filtered from results."""
        cash_cursor = _cursor_with_cash()
        pos_cursor = _cursor_with_positions(
            [
                {"symbol": "A", "qty": Decimal("0")},  # zero — filtered
                {"symbol": "B", "qty": Decimal("50")},  # non-zero — kept
            ]
        )
        pool = _FakePool([_FakeConn(cash_cursor), _FakeConn(pos_cursor)])

        loader = AccountStateLoader(pool=pool)
        view = _run(loader.load_account_view())

        assert view.position("A").qty == Decimal("0")  # unknown symbol
        assert view.position("B").qty == Decimal("50")

    def test_db_connection_error_returns_zero_state(self):
        """Connection failure gracefully returns zero-state AccountView."""
        pool = MagicMock()
        pool.connection.side_effect = RuntimeError("connection refused")

        loader = AccountStateLoader(pool=pool)
        view = _run(loader.load_account_view())

        assert view.cash == Decimal("0")
        assert view.available_cash == Decimal("0")  # from _load_cash fallback
        assert view.positions == {} or len(view.positions) == 0  # type: ignore[arg-type]

    def test_load_positions_table_missing_returns_empty(self):
        """When live_positions table doesn't exist, returns empty positions."""
        cash_cursor = _cursor_with_cash(Decimal("50000"), Decimal("50000"))
        pos_cursor = _cursor_with_error(RuntimeError('relation "live_positions" does not exist'))
        pool = _FakePool([_FakeConn(cash_cursor), _FakeConn(pos_cursor)])

        loader = AccountStateLoader(pool=pool)
        view = _run(loader.load_account_view())

        assert view.cash == Decimal("50000")
        assert view.available_cash == Decimal("50000")
        assert view.positions == {} or len(view.positions) == 0  # type: ignore[arg-type]

    def test_load_cash_table_missing_returns_zero_cash(self):
        """When live_account_state table doesn't exist, returns zero cash."""
        cash_cursor = _cursor_with_error(
            RuntimeError('relation "live_account_state" does not exist')
        )
        pos_cursor = _cursor_with_positions([])
        pool = _FakePool([_FakeConn(cash_cursor), _FakeConn(pos_cursor)])

        loader = AccountStateLoader(pool=pool)
        view = _run(loader.load_account_view())

        assert view.cash == Decimal("0")
        assert view.available_cash == Decimal("0")

    def test_decimal_type_consistency(self):
        """All monetary values are Decimal."""
        cash_cursor = _cursor_with_cash(Decimal("99999.99"), Decimal("12345.67"))
        pos_cursor = _cursor_with_positions(
            [
                {"symbol": "A", "qty": Decimal("100.5")},
            ]
        )
        pool = _FakePool([_FakeConn(cash_cursor), _FakeConn(pos_cursor)])

        loader = AccountStateLoader(pool=pool)
        view = _run(loader.load_account_view())

        assert isinstance(view.cash, Decimal)
        assert isinstance(view.available_cash, Decimal)
        assert isinstance(view.position("A").qty, Decimal)

    def test_custom_pool_accepted(self):
        """AccountStateLoader accepts a custom pool instance."""
        pool = MagicMock()
        loader = AccountStateLoader(pool=pool)
        assert loader._pool is pool

    def test_default_pool_is_pg_pool(self):
        """Default constructor uses the global pg_pool singleton."""
        from getrich.apps.strategy.account_loader import pg_pool as default_pool

        loader = AccountStateLoader()
        assert loader._pool is default_pool


class TestDataProviderIntegration:
    """Tests for LiveDataProvider + AccountStateLoader integration."""

    def test_provider_without_loader_returns_zero_account(self):
        """Default data provider creates zero-state AccountView."""
        from contextlib import AbstractContextManager
        from datetime import datetime

        import pandas as pd

        from getrich.apps.strategy.live_data_provider import LiveDataProvider

        tz = __import__("getrich_backtest", fromlist=["get_shanghai_tz"]).get_shanghai_tz()

        class _TestClient:
            def query(self, sql, params=None):
                return pd.DataFrame(
                    {
                        "dt": [datetime(2026, 6, 1, 9, 30, tzinfo=tz)],
                        "symbol": ["A"],
                        "open": [10.0],
                        "high": [10.2],
                        "low": [9.9],
                        "close": [10.1],
                        "volume": [1000.0],
                    }
                )

        class _TestPool:
            def connection(self):
                return _TestConnCtxMgr(_TestClient())

        class _TestConnCtxMgr(AbstractContextManager):
            def __init__(self, client):
                self._client = client

            def __enter__(self):
                return self._client

            def __exit__(self, *a):
                pass

        provider = LiveDataProvider(pool=_TestPool())  # type: ignore[arg-type]
        ctx = _run(provider.build_context(["A"]))

        assert ctx is not None
        assert ctx.account.cash == Decimal("0")
        assert ctx.account.available_cash == Decimal("0")

    def test_provider_with_loader_uses_real_account(self):
        """Data provider with loader uses real account state."""
        from contextlib import AbstractContextManager
        from datetime import datetime

        import pandas as pd

        from getrich.apps.strategy.live_data_provider import LiveDataProvider

        tz = __import__("getrich_backtest", fromlist=["get_shanghai_tz"]).get_shanghai_tz()

        class _TestClient:
            def query(self, sql, params=None):
                return pd.DataFrame(
                    {
                        "dt": [datetime(2026, 6, 1, 9, 30, tzinfo=tz)],
                        "symbol": ["A"],
                        "open": [10.0],
                        "high": [10.2],
                        "low": [9.9],
                        "close": [10.1],
                        "volume": [1000.0],
                    }
                )

        class _TestPool:
            def connection(self):
                return _TestConnCtxMgr(_TestClient())

        class _TestConnCtxMgr(AbstractContextManager):
            def __init__(self, client):
                self._client = client

            def __enter__(self):
                return self._client

            def __exit__(self, *a):
                pass

        # Create an account loader with mock pool
        cash_cursor = _cursor_with_cash(Decimal("88888"), Decimal("77777"))
        pos_cursor = _cursor_with_positions([])
        loader_pool = _FakePool([_FakeConn(cash_cursor), _FakeConn(pos_cursor)])
        loader = AccountStateLoader(pool=loader_pool)

        provider = LiveDataProvider(pool=_TestPool(), account_loader=loader)  # type: ignore[arg-type]
        ctx = _run(provider.build_context(["A"]))

        assert ctx is not None
        assert ctx.account.cash == Decimal("88888")
        assert ctx.account.available_cash == Decimal("77777")
