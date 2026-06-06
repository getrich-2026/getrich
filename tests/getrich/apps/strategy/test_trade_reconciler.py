"""Tests for reconcile_trades — PnL backfill in strategy_trades."""

from __future__ import annotations

from getrich.apps.strategy.trade_reconciler import backfill_trade_gaps, reconcile_trades


# ---------------------------------------------------------------------------
# AVCO computation (unit tests without DB)
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Simulates a strategy_trades query result set."""

    def __init__(self, rows=None) -> None:
        self._rows = rows or []
        self.executed: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def execute(self, sql, params=None):
        self.executed.append((sql, params))

    async def fetchall(self):
        return list(self._rows)


class _FakeConn:
    def __init__(self, cursor=None) -> None:
        self._cursor = cursor
        self.committed = False

    def cursor(self):
        return self._cursor

    async def commit(self):
        self.committed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class _FakePool:
    def __init__(self, conn=None) -> None:
        self._conn = conn

    def connection(self):
        return self

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass


def _row(trade_id, symbol, action, quantity, price, notional, fee="0"):
    return {
        "id": trade_id,
        "symbol": symbol,
        "action": action,
        "quantity": quantity,
        "price": price,
        "notional": notional,
        "fee": fee,
        "executed_at": None,
    }


def _run(coro):
    import asyncio

    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReconcileBasic:
    def test_empty_trades_returns_zero(self):
        cur = _FakeCursor([])
        conn = _FakeConn(cur)
        pool = _FakePool(conn)

        result = _run(reconcile_trades("sid-1", pool=pool))
        assert result == 0

    def test_single_buy_no_update_needed(self):
        rows = [_row("t1", "A", "buy", "100", "50", "5000")]
        cur = _FakeCursor(rows)
        conn = _FakeConn(cur)
        pool = _FakePool(conn)

        result = _run(reconcile_trades("sid-1", pool=pool))
        # avg_cost=None, realized_pnl=0, cumulative_pnl=0 — 1 UPDATE
        assert result == 1
        updates = [c for c in cur.executed if "UPDATE" in (c[0] or "")]
        assert "bar_dt = COALESCE(bar_dt, executed_at)" in updates[0][0]


class TestReconcileAVCO:
    def test_buy_then_sell_updates_pnl(self):
        rows = [
            _row("t1", "A", "buy", "100", "50", "5000"),
            _row("t2", "A", "sell", "100", "55", "5500"),
        ]
        cur = _FakeCursor(rows)
        conn = _FakeConn(cur)
        pool = _FakePool(conn)

        result = _run(reconcile_trades("sid-1", pool=pool))
        assert result == 2

        # Check UPDATE calls — second one should have PnL
        updates = [c for c in cur.executed if "UPDATE" in (c[0] or "")]
        assert len(updates) == 2
        # Buy update: avg_cost=None, realized_pnl=0.00
        assert updates[0][1]["realized_pnl"] == "0.00"
        # Sell update: avg_cost=50, realized_pnl=500
        assert updates[1][1]["avg_cost"] == "50.00"
        assert updates[1][1]["realized_pnl"] == "500.00"

    def test_multi_symbol_isolation(self):
        rows = [
            _row("t1", "A", "buy", "100", "10", "1000"),
            _row("t2", "B", "buy", "100", "20", "2000"),
            _row("t3", "A", "sell", "100", "15", "1500"),
            _row("t4", "B", "sell", "100", "18", "1800"),
        ]
        cur = _FakeCursor(rows)
        conn = _FakeConn(cur)
        pool = _FakePool(conn)

        result = _run(reconcile_trades("sid-1", pool=pool))
        assert result == 4

        updates = [c for c in cur.executed if "UPDATE" in (c[0] or "")]
        # A sell: profit 500
        assert updates[2][1]["realized_pnl"] == "500.00"
        # B sell: loss 200
        assert updates[3][1]["realized_pnl"] == "-200.00"

    def test_partial_sell(self):
        rows = [
            _row("t1", "A", "buy", "200", "50", "10000"),
            _row("t2", "A", "sell", "100", "55", "5500"),
        ]
        cur = _FakeCursor(rows)
        conn = _FakeConn(cur)
        pool = _FakePool(conn)

        result = _run(reconcile_trades("sid-1", pool=pool))
        assert result == 2

        updates = [c for c in cur.executed if "UPDATE" in (c[0] or "")]
        assert updates[1][1]["realized_pnl"] == "500.00"
        assert updates[1][1]["cumulative_pnl"] == "500.00"

    def test_cumulative_pnl_accumulates(self):
        rows = [
            _row("t1", "X", "buy", "100", "10", "1000"),
            _row("t2", "X", "sell", "50", "12", "600"),
            _row("t3", "X", "sell", "50", "8", "400"),
        ]
        cur = _FakeCursor(rows)
        conn = _FakeConn(cur)
        pool = _FakePool(conn)

        result = _run(reconcile_trades("sid-1", pool=pool))
        assert result == 3

        updates = [c for c in cur.executed if "UPDATE" in (c[0] or "")]
        assert updates[1][1]["realized_pnl"] == "100.00"
        assert updates[1][1]["cumulative_pnl"] == "100.00"
        assert updates[2][1]["realized_pnl"] == "-100.00"
        assert updates[2][1]["cumulative_pnl"] == "0.00"

    def test_connect_via_conn_parameter(self):
        rows = [_row("t1", "A", "buy", "100", "50", "5000")]
        cur = _FakeCursor(rows)
        conn = _FakeConn(cur)

        result = _run(reconcile_trades("sid-1", conn=conn))
        assert result == 1
        # conn parameter path should NOT commit (caller controls)
        assert not conn.committed

    def test_connect_via_pool_commits(self):
        rows = [_row("t1", "A", "buy", "100", "50", "5000")]
        cur = _FakeCursor(rows)
        conn = _FakeConn(cur)
        pool = _FakePool(conn)

        result = _run(reconcile_trades("sid-1", pool=pool))
        assert result == 1
        assert conn.committed


class _SequencedCursor:
    """Cursor that returns one fetchall result per SELECT call."""

    def __init__(self, results: list[list[dict]]) -> None:
        self._results = results
        self.executed: list[tuple[str, dict | None]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def execute(self, sql, params=None):
        self.executed.append((sql, params))

    async def fetchall(self):
        return self._results.pop(0) if self._results else []


class TestBackfillTradeGaps:
    def test_backfill_repairs_bar_dt_and_reconciles_affected_strategies(self):
        rows = [
            [{"strategy_id": "sid-1"}, {"strategy_id": "sid-2"}],
            [_row("t1", "A", "buy", "100", "10", "1000")],
            [_row("t2", "B", "buy", "100", "20", "2000")],
        ]
        cur = _SequencedCursor(rows)
        conn = _FakeConn(cur)

        result = _run(backfill_trade_gaps(conn=conn))

        assert result == 2
        sqls = [sql for sql, _ in cur.executed]
        assert any("cumulative_pnl IS NULL OR bar_dt IS NULL" in sql for sql in sqls)
        assert any("SET bar_dt = s.published_at" in sql for sql in sqls)
        assert any("SET bar_dt = executed_at" in sql for sql in sqls)
        assert sum("UPDATE strategy_trades" in sql for sql in sqls) == 4
        assert not conn.committed

    def test_backfill_pool_path_commits(self):
        cur = _SequencedCursor(
            [[{"strategy_id": "sid-1"}], [_row("t1", "A", "buy", "100", "10", "1000")]]
        )
        conn = _FakeConn(cur)
        pool = _FakePool(conn)

        result = _run(backfill_trade_gaps(pool=pool))

        assert result == 1
        assert conn.committed

    def test_backfill_no_affected_strategies_returns_zero(self):
        cur = _SequencedCursor([[]])
        conn = _FakeConn(cur)
        pool = _FakePool(conn)

        result = _run(backfill_trade_gaps(pool=pool))

        assert result == 0
        assert conn.committed
