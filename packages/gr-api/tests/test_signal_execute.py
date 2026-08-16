"""Tests for signal execution service behavior."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from gr_api.schemas.signal import ExecuteSignalIn
from gr_api.services import signal as signal_service


class _FakeCursor:
    """Mock async cursor with sequential fetchone results."""

    def __init__(self, rows: list[dict | None]) -> None:
        self._rows = rows
        self.executed: list[tuple[str, object]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def execute(self, sql, params=None):
        self.executed.append((sql, params))

    async def fetchone(self):
        return self._rows.pop(0) if self._rows else None


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.committed = False

    def cursor(self):
        return self._cursor

    async def commit(self):
        self.committed = True


def _run(coro):
    import asyncio

    return asyncio.new_event_loop().run_until_complete(coro)


class TestRecordExecute:
    def test_writes_bar_dt_and_reconciles_before_commit(self, monkeypatch) -> None:
        published_at = datetime(2026, 6, 1, 9, 30)
        executed_at = datetime(2026, 6, 1, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        cursor = _FakeCursor(
            [
                {
                    "trigger_price": Decimal("10.00"),
                    "symbol": "000001.SZ",
                    "action": "buy",
                    "strategy_id": "strat-1",
                    "published_at": published_at,
                }
            ]
        )
        conn = _FakeConn(cursor)
        calls: list[tuple[str, object, bool]] = []

        async def _fake_reconcile(strategy_id, *, conn=None, pool=None):
            calls.append((strategy_id, conn, conn.committed))
            return 1

        monkeypatch.setattr(signal_service, "reconcile_trades", _fake_reconcile)

        result = _run(
            signal_service.record_execute(
                conn,
                user_id="user-1",
                signal_id="sig-1",
                signal_code="SIG001",
                body=ExecuteSignalIn(
                    executed_price=10.5,
                    executed_quantity=100,
                    executed_at=executed_at,
                    note="manual fill",
                ),
            )
        )

        assert result["signal_id"] == "SIG001"
        assert result["is_executed"] is True
        assert result["slippage"] == 0.5
        assert conn.committed
        assert calls == [("strat-1", conn, False)]

        select_sql, _ = cursor.executed[0]
        assert "published_at" in select_sql

        trade_sql, trade_params = cursor.executed[2]
        assert "bar_dt" in trade_sql
        assert trade_params[10] == executed_at
        assert trade_params[11] == published_at
        assert trade_params[12] == "manual fill"

    def test_falls_back_to_executed_at_when_signal_has_no_published_at(self, monkeypatch) -> None:
        executed_at = datetime(2026, 6, 1, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        cursor = _FakeCursor(
            [
                {
                    "trigger_price": Decimal("10.00"),
                    "symbol": "000001.SZ",
                    "action": "sell",
                    "strategy_id": "strat-1",
                    "published_at": None,
                }
            ]
        )
        conn = _FakeConn(cursor)

        async def _fake_reconcile(strategy_id, *, conn=None, pool=None):
            return 1

        monkeypatch.setattr(signal_service, "reconcile_trades", _fake_reconcile)

        _run(
            signal_service.record_execute(
                conn,
                user_id="user-1",
                signal_id="sig-1",
                signal_code="SIG001",
                body=ExecuteSignalIn(
                    executed_price=9.5,
                    executed_quantity=100,
                    executed_at=executed_at,
                ),
            )
        )

        _, trade_params = cursor.executed[2]
        assert trade_params[11] == executed_at
