"""Tests for ``list_signals_of_strategy``.

`services.strategy.list_signals_of_strategy` powers
``GET /strategies/{code}/signals`` — the strategy-scoped signal
list (vs. ``/signals`` which is the global user dashboard feed).
A key contract difference from ``services.signal.list_signals``:

- This endpoint does NOT have a `user_id` parameter, so the
  response's `is_read` and `is_executed` fields are hard-coded
  to `False`. The "Mark as read" / "Mark as executed" semantics
  belong to the global user feed (``services.signal``), not to
  the public strategy page.

The query has three optional filters (all with the same
`"all"` sentinel pattern):
- `type_` — `'entry'` / `'exit'` / `'adjust'` / `'alert'`
- `action` — `'buy'` / `'sell'` / `'hold'` / `'close'`
- `status` — `'active'` / `'expired'` / `'cancelled'`
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from gr_api.services.strategy import list_signals_of_strategy


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Mock async cursor. `set_rows` queues a `fetchall` response."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, Any] | tuple]] = []
        self._fetchall_q: list[list[dict[str, Any]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def execute(self, sql, params=None):
        self.executed.append((sql.strip(), params))

    async def fetchall(self) -> list[dict[str, Any]]:
        if self._fetchall_q:
            return self._fetchall_q.pop(0)
        return []

    async def fetchone(self):  # pragma: no cover
        return None

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self._fetchall_q.append(rows)


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class _Page:
    def __init__(self, limit: int = 20, offset: int = 0) -> None:
        self.limit = limit
        self.offset = offset


def _signal_row(
    *,
    id: str = "SIG_20260601_001",
    signal_type: str = "entry",
    action: str = "buy",
    symbol: str = "rb2410",
    trigger_price: float = 3500.0,
    confidence: float = 0.85,
    urgency: str = "high",
    trigger_time: datetime | None = None,
    status: str = "active",
    total_count: int = 1,
) -> dict[str, Any]:
    return {
        "id": id,
        "signal_type": signal_type,
        "action": action,
        "symbol": symbol,
        "trigger_price": trigger_price,
        "confidence": confidence,
        "urgency": urgency,
        "trigger_time": trigger_time or datetime(2026, 6, 1, 9, 30, tzinfo=timezone.utc),
        "status": status,
        "_total": total_count,
    }


# ---------------------------------------------------------------------------
# list_signals_of_strategy
# ---------------------------------------------------------------------------


async def test_list_signals_strategy_id_always_in_where() -> None:
    """`strategy_id` is the tenant key — always in WHERE."""
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_signals_of_strategy(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        type_=None,
        action=None,
        status=None,
        page=_Page(),
    )

    sql, params = cursor.executed[0]
    assert "WHERE strategy_id = %(sid)s" in sql
    assert params["sid"] == "strat-uuid-1"


async def test_list_signals_empty_result_returns_empty_tuple() -> None:
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    items, total = await list_signals_of_strategy(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        type_=None,
        action=None,
        status=None,
        page=_Page(),
    )

    assert items == []
    assert total == 0


async def test_list_signals_pagination_params() -> None:
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_signals_of_strategy(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        type_=None,
        action=None,
        status=None,
        page=_Page(limit=50, offset=200),
    )

    params = cursor.executed[0][1]
    assert params["limit"] == 50
    assert params["offset"] == 200


async def test_list_signals_type_filter_specific_value() -> None:
    """`type_='entry'` (or `'exit'` / `'adjust'` / `'alert'`) adds
    an equality predicate. The frontend uses this for the type
    tabs in the strategy page's signal list."""
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_signals_of_strategy(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        type_="entry",
        action=None,
        status=None,
        page=_Page(),
    )

    sql, params = cursor.executed[0]
    assert "type = %(type)s" in sql
    assert params["type"] == "entry"


async def test_list_signals_type_all_sentinel_passes_through() -> None:
    """`type_='all'` (the frontend's "all types" tab) is treated
    as no filter — the conds loop skips it via the
    `type_ != "all"` guard."""
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_signals_of_strategy(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        type_="all",
        action=None,
        status=None,
        page=_Page(),
    )

    sql, params = cursor.executed[0]
    assert "type = %(type)s" not in sql
    assert "type" not in params


async def test_list_signals_action_filter_specific_value() -> None:
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_signals_of_strategy(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        type_=None,
        action="buy",
        status=None,
        page=_Page(),
    )

    sql, params = cursor.executed[0]
    assert "action = %(action)s" in sql
    assert params["action"] == "buy"


async def test_list_signals_action_all_sentinel_passes_through() -> None:
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_signals_of_strategy(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        type_=None,
        action="all",
        status=None,
        page=_Page(),
    )

    sql, params = cursor.executed[0]
    assert "action = %(action)s" not in sql


async def test_list_signals_status_filter_specific_value() -> None:
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_signals_of_strategy(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        type_=None,
        action=None,
        status="active",
        page=_Page(),
    )

    sql, params = cursor.executed[0]
    assert "status = %(status)s" in sql
    assert params["status"] == "active"


async def test_list_signals_status_all_sentinel_passes_through() -> None:
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_signals_of_strategy(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        type_=None,
        action=None,
        status="all",
        page=_Page(),
    )

    sql, params = cursor.executed[0]
    assert "status = %(status)s" not in sql


async def test_list_signals_is_read_is_executed_always_false() -> None:
    """The strategy-scoped signal view is public — there's no
    `user_id` parameter, so the response's `is_read` and
    `is_executed` flags are hard-coded to `False`. This is a
    key contract difference from `services.signal.list_signals`
    which DOES user-join those flags. The frontend uses this
    to disable the "Mark as read" button on the public page.
    """
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _signal_row(),
        ]
    )
    conn = _FakeConn(cursor)

    items, _ = await list_signals_of_strategy(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        type_=None,
        action=None,
        status=None,
        page=_Page(),
    )

    assert items[0]["is_read"] is False
    assert items[0]["is_executed"] is False


async def test_list_signals_serializes_trigger_time_to_iso() -> None:
    """`trigger_time` is renamed from the DB's `published_at`
    column and serialized to ISO format."""
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _signal_row(
                trigger_time=datetime(2026, 6, 1, 9, 30, tzinfo=timezone.utc),
            )
        ]
    )
    conn = _FakeConn(cursor)

    items, _ = await list_signals_of_strategy(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        type_=None,
        action=None,
        status=None,
        page=_Page(),
    )

    assert items[0]["trigger_time"] == "2026-06-01T09:30:00+00:00"


async def test_list_signals_output_schema() -> None:
    """The output dict has the public schema: id, signal_type,
    action, symbol, trigger_price, confidence, urgency,
    trigger_time, is_read, is_executed, status. The
    `strategy` sub-dict is NOT included here (vs.
    `services.signal.list_signals` which inlines it) — the
    strategy code is already in the URL path, so the frontend
    doesn't need it in the payload."""
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _signal_row(
                id="SIG_20260601_001",
                signal_type="entry",
                action="buy",
                symbol="rb2410",
                trigger_price=3500.0,
                confidence=0.85,
                urgency="high",
                status="active",
            )
        ]
    )
    conn = _FakeConn(cursor)

    items, total = await list_signals_of_strategy(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        type_=None,
        action=None,
        status=None,
        page=_Page(),
    )

    assert total == 1
    item = items[0]
    assert item["id"] == "SIG_20260601_001"
    assert item["signal_type"] == "entry"
    assert item["action"] == "buy"
    assert item["symbol"] == "rb2410"
    assert item["trigger_price"] == 3500.0
    assert item["confidence"] == 0.85
    assert item["urgency"] == "high"
    assert item["status"] == "active"
    # is_read / is_executed hard-coded False
    assert item["is_read"] is False
    assert item["is_executed"] is False
    # No `strategy` sub-dict — the strategy code is in the URL.
    assert "strategy" not in item


async def test_list_signals_ordered_by_published_at_desc() -> None:
    """Most recent signals first — the standard timeline view."""
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_signals_of_strategy(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        type_=None,
        action=None,
        status=None,
        page=_Page(),
    )

    sql = cursor.executed[0][0]
    assert "ORDER BY published_at DESC" in sql


async def test_list_signals_combines_all_filters() -> None:
    """All three filter values are passed to params
    simultaneously. Guards against an accidental refactor that
    drops one of the conds entries."""
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_signals_of_strategy(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        type_="entry",
        action="buy",
        status="active",
        page=_Page(),
    )

    sql, params = cursor.executed[0]
    assert "type = %(type)s" in sql
    assert "action = %(action)s" in sql
    assert "status = %(status)s" in sql
    assert params["type"] == "entry"
    assert params["action"] == "buy"
    assert params["status"] == "active"
