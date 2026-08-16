"""Tests for strategy_trades service layer (list_trades)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from gr_api.pagination import PageParams
from gr_api.services.strategy import list_trades


_TZ_DT = datetime(2026, 6, 1, 10, 30)
_PAGE = PageParams(page=1, page_size=20)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Mock async cursor with configurable fetchall results."""

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
    """Mock async connection."""

    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self):
        return self._cursor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trade_row(
    *,
    trade_id: str = "t-001",
    strategy_id: str = "strat-1",
    signal_id: str | None = "sig-1",
    symbol: str = "000001.SZ",
    action: str = "buy",
    quantity: Decimal = Decimal("100"),
    price: Decimal = Decimal("10.50"),
    notional: Decimal = Decimal("1050"),
    fee: Decimal = Decimal("5"),
    slippage: Decimal = Decimal("0.01"),
    avg_cost: Decimal | None = None,
    realized_pnl: Decimal = Decimal("0"),
    cumulative_pnl: Decimal | None = None,
    executed_at: datetime | None = None,
    bar_dt: datetime | None = None,
    tag: str | None = None,
    _total: int = 1,
) -> dict:
    return {
        "_total": _total,
        "action": action,
        "avg_cost": avg_cost,
        "bar_dt": bar_dt or _TZ_DT,
        "cumulative_pnl": cumulative_pnl,
        "executed_at": executed_at or _TZ_DT,
        "fee": fee,
        "id": trade_id,
        "notional": notional,
        "price": price,
        "quantity": quantity,
        "realized_pnl": realized_pnl,
        "signal_id": signal_id,
        "slippage": slippage,
        "strategy_id": strategy_id,
        "symbol": symbol,
        "tag": tag,
    }


def _run(coro):
    """Run a coroutine synchronously via a fresh event loop."""
    import asyncio

    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestListTrades:
    def test_empty_returns_zero(self) -> None:
        cursor = _FakeCursor([])
        conn = _FakeConn(cursor)
        items, total = _run(
            list_trades(
                conn,
                strategy_id="strat-1",
                strategy_code="STR_001",
                start_date=None,
                end_date=None,
                action=None,
                result=None,
                page=_PAGE,
            )
        )
        assert items == []
        assert total == 0

    def test_all_returns_all_rows(self) -> None:
        rows = [
            _make_trade_row(trade_id="t-1", action="buy", _total=3),
            _make_trade_row(trade_id="t-2", action="sell", realized_pnl=Decimal("150"), _total=3),
            _make_trade_row(trade_id="t-3", action="sell", realized_pnl=Decimal("-50"), _total=3),
        ]
        cursor = _FakeCursor(rows)
        conn = _FakeConn(cursor)
        items, total = _run(
            list_trades(
                conn,
                strategy_id="strat-1",
                strategy_code="STR_001",
                start_date=None,
                end_date=None,
                action=None,
                result=None,
                page=_PAGE,
            )
        )

        assert len(items) == 3
        assert total == 3
        assert [i["id"] for i in items] == ["t-1", "t-2", "t-3"]

    def test_filter_action_buy(self) -> None:
        cursor = _FakeCursor([_make_trade_row(trade_id="t-1", action="buy", _total=1)])
        conn = _FakeConn(cursor)
        _run(
            list_trades(
                conn,
                strategy_id="strat-1",
                strategy_code="STR_001",
                start_date=None,
                end_date=None,
                action="buy",
                result=None,
                page=_PAGE,
            )
        )

        sql = cursor.executed[0][0]
        params = cursor.executed[0][1]
        assert "action = %(action)s" in sql
        assert params["action"] == "buy"

    def test_filter_action_sell(self) -> None:
        cursor = _FakeCursor([_make_trade_row(trade_id="t-2", action="sell", _total=1)])
        conn = _FakeConn(cursor)
        _run(
            list_trades(
                conn,
                strategy_id="strat-1",
                strategy_code="STR_001",
                start_date=None,
                end_date=None,
                action="sell",
                result=None,
                page=_PAGE,
            )
        )

        params = cursor.executed[0][1]
        assert params["action"] == "sell"

    def test_filter_result_win(self) -> None:
        """result=win adds 'realized_pnl > 0' to WHERE clause."""
        cursor = _FakeCursor(
            [_make_trade_row(trade_id="t-w", realized_pnl=Decimal("100"), _total=1)]
        )
        conn = _FakeConn(cursor)
        _run(
            list_trades(
                conn,
                strategy_id="strat-1",
                strategy_code="STR_001",
                start_date=None,
                end_date=None,
                action=None,
                result="win",
                page=_PAGE,
            )
        )

        sql = cursor.executed[0][0]
        assert "realized_pnl > 0" in sql

    def test_filter_result_loss(self) -> None:
        """result=loss adds 'realized_pnl < 0' to WHERE clause."""
        cursor = _FakeCursor(
            [_make_trade_row(trade_id="t-l", realized_pnl=Decimal("-50"), _total=1)]
        )
        conn = _FakeConn(cursor)
        _run(
            list_trades(
                conn,
                strategy_id="strat-1",
                strategy_code="STR_001",
                start_date=None,
                end_date=None,
                action=None,
                result="loss",
                page=_PAGE,
            )
        )

        sql = cursor.executed[0][0]
        assert "realized_pnl < 0" in sql

    def test_filter_date_range(self) -> None:
        cursor = _FakeCursor([_make_trade_row(_total=1)])
        conn = _FakeConn(cursor)
        _run(
            list_trades(
                conn,
                strategy_id="strat-1",
                strategy_code="STR_001",
                start_date=date(2026, 1, 1),
                end_date=date(2026, 6, 30),
                action=None,
                result=None,
                page=_PAGE,
            )
        )

        sql = cursor.executed[0][0]
        params = cursor.executed[0][1]
        assert "executed_at >=" in sql
        assert "executed_at <" in sql
        assert params["start"] == date(2026, 1, 1)
        assert params["end"] == date(2026, 6, 30)

    def test_pagination_params(self) -> None:
        cursor = _FakeCursor([_make_trade_row(_total=5)])
        conn = _FakeConn(cursor)
        _run(
            list_trades(
                conn,
                strategy_id="strat-1",
                strategy_code="STR_001",
                start_date=None,
                end_date=None,
                action=None,
                result=None,
                page=PageParams(page=2, page_size=10),
            )
        )

        params = cursor.executed[0][1]
        assert params["limit"] == 10
        assert params["offset"] == 10  # (page-1) * page_size

    def test_total_extracted_from_window_function(self) -> None:
        rows = [
            _make_trade_row(trade_id="a", _total=42),
            _make_trade_row(trade_id="b", _total=42),
        ]
        cursor = _FakeCursor(rows)
        conn = _FakeConn(cursor)
        items, total = _run(
            list_trades(
                conn,
                strategy_id="strat-1",
                strategy_code="STR_001",
                start_date=None,
                end_date=None,
                action=None,
                result=None,
                page=_PAGE,
            )
        )

        assert len(items) == 2
        assert total == 42

    def test_field_serialization(self) -> None:
        rows = [
            _make_trade_row(
                trade_id="t-f",
                symbol="000001.SZ",
                action="sell",
                quantity=Decimal("200"),
                price=Decimal("15.25"),
                notional=Decimal("3050"),
                fee=Decimal("3"),
                slippage=Decimal("-0.02"),
                avg_cost=Decimal("10.00"),
                realized_pnl=Decimal("1050"),
                cumulative_pnl=Decimal("5000"),
                tag="test trade",
            ),
        ]
        cursor = _FakeCursor(rows)
        conn = _FakeConn(cursor)
        items, _ = _run(
            list_trades(
                conn,
                strategy_id="strat-1",
                strategy_code="STR_001",
                start_date=None,
                end_date=None,
                action=None,
                result=None,
                page=_PAGE,
            )
        )

        item = items[0]
        assert item["strategy_id"] == "strat-1"
        assert item["signal_id"] == "sig-1"
        # Numeric fields should be float
        assert isinstance(item["quantity"], float)
        assert item["quantity"] == 200.0
        assert isinstance(item["price"], float)
        assert item["price"] == 15.25
        assert isinstance(item["notional"], float)
        assert isinstance(item["fee"], float)
        assert isinstance(item["slippage"], float)
        assert isinstance(item["avg_cost"], float)
        assert isinstance(item["realized_pnl"], float)
        assert isinstance(item["cumulative_pnl"], float)
        # Datetime → ISO string
        assert isinstance(item["executed_at"], str)
        assert "T" in item["executed_at"]
        assert isinstance(item["bar_dt"], str)
        assert "T" in item["bar_dt"]
        # Tag preserved
        assert item["tag"] == "test trade"

    def test_nullable_trade_fields_are_preserved(self) -> None:
        cursor = _FakeCursor(
            [
                _make_trade_row(
                    signal_id=None,
                    avg_cost=None,
                    cumulative_pnl=None,
                    bar_dt=None,
                )
            ]
        )
        conn = _FakeConn(cursor)
        items, _ = _run(
            list_trades(
                conn,
                strategy_id="strat-1",
                strategy_code="STR_001",
                start_date=None,
                end_date=None,
                action=None,
                result=None,
                page=_PAGE,
            )
        )

        assert items[0]["signal_id"] is None
        assert items[0]["avg_cost"] is None
        assert items[0]["cumulative_pnl"] is None

    def test_tag_null_defaults_to_empty_string(self) -> None:
        cursor = _FakeCursor([_make_trade_row(tag=None)])
        conn = _FakeConn(cursor)
        items, _ = _run(
            list_trades(
                conn,
                strategy_id="strat-1",
                strategy_code="STR_001",
                start_date=None,
                end_date=None,
                action=None,
                result=None,
                page=_PAGE,
            )
        )
        assert items[0]["tag"] == ""
