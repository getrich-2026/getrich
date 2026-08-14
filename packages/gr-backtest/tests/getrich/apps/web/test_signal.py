"""Tests for the signal service.

`services.signal` is the main dashboard feed: `list_signals` is a
multi-cursor query with conditional user-JOIN, `unread_summary`
aggregates across 3 SELECTs, and `mark_read` is a UPSERT. The
`record_execute` path is exercised end-to-end by the live trade
reconciler (transitively imports `getrich.apps.strategy` and ClickHouse
readers) so we skip it here.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import pytest

from getrich.apps.web.services.signal import (
    list_signals,
    mark_read,
    unread_summary,
)


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Mock async cursor. `fetchall` returns a list-of-rows set via
    `set_rows`, `fetchone` returns the next row pushed via `push_one`
    (FIFO). The test must pre-load the right number of rows in the
    right order — see comments below.
    """

    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, Any] | tuple | None]] = []
        self._fetchall_rows: list[list[dict[str, Any]]] = []
        self._fetchone_q: list[dict[str, Any] | None] = []
        self._calls: int = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def execute(self, sql, params=None):
        self.executed.append((sql.strip(), params))
        self._calls += 1

    async def fetchall(self) -> list[dict[str, Any]]:
        if self._fetchall_rows:
            return self._fetchall_rows.pop(0)
        return []

    async def fetchone(self) -> dict[str, Any] | None:
        if self._fetchone_q:
            return self._fetchone_q.pop(0)
        return None

    # Test helpers
    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        """Queue a result for the NEXT `fetchall` call."""
        self._fetchall_rows.append(rows)

    def push_one(self, row: dict[str, Any] | None) -> None:
        """Queue a result for the NEXT `fetchone` call."""
        self._fetchone_q.append(row)


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.commits: int = 0

    def cursor(self):
        return self._cursor

    async def commit(self) -> None:
        self.commits += 1


class _Page:
    """Minimal PageParams stand-in (only `limit` and `offset` used)."""

    def __init__(self, limit: int = 20, offset: int = 0) -> None:
        self.limit = limit
        self.offset = offset


# ---------------------------------------------------------------------------
# list_signals
# ---------------------------------------------------------------------------


def _row(
    *,
    signal_id: str = "sig-1",
    strategy_code: str = "STR_FUT_001",
    strategy_name: str = "Fut 001",
    type: str = "entry",
    action: str = "buy",
    direction: str | None = "long",
    symbol: str = "rb2410",
    symbol_name: str = "螺纹",
    exchange: str = "SHFE",
    trigger_price: float | None = 3500.0,
    target_price: float | None = 3600.0,
    stop_loss_price: float | None = 3450.0,
    confidence: float = 0.85,
    urgency: str = "high",
    reason: str = "突破",
    published_at: datetime | None = None,
    status: str = "active",
    is_read: bool = False,
    is_executed: bool = False,
    total: int = 1,
) -> dict[str, Any]:
    return {
        "id": signal_id,
        "strategy_code": strategy_code,
        "strategy_name": strategy_name,
        "signal_type": type,
        "action": action,
        "direction": direction,
        "symbol": symbol,
        "symbol_name": symbol_name,
        "exchange": exchange,
        "trigger_price": trigger_price,
        "target_price": target_price,
        "stop_loss_price": stop_loss_price,
        "confidence": confidence,
        "urgency": urgency,
        "reason": reason,
        "trigger_time": published_at or datetime(2026, 5, 1, 9, 30, tzinfo=timezone.utc),
        "status": status,
        "is_read": is_read,
        "is_executed": is_executed,
        "_total": total,
    }


async def test_list_signals_anonymous_filters_to_no_user_state() -> None:
    """For `user_id=None`, the service issues a single SELECT (no
    `user_signal_reads` join, no unread summary) and returns
    `unread_count=0` with `is_read=False` for every item.
    """
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _row(signal_id="sig-1", is_read=False, is_executed=False),
            _row(signal_id="sig-2", is_read=False, is_executed=False),
        ]
    )
    conn = _FakeConn(cursor)

    items, total, unread = await list_signals(
        conn,  # type: ignore[arg-type]
        user_id=None,
        strategy_id=None,
        strategy_ids=None,
        signal_type=None,
        action=None,
        asset_class=None,
        is_read=None,
        confidence_min=None,
        start_date=None,
        end_date=None,
        page=_Page(),
    )

    assert total == 1  # _total from first row, both rows share it
    assert unread == 0
    assert len(items) == 2
    for item in items:
        assert item["is_read"] is False
        assert item["is_executed"] is False
    # Only one SELECT (no unread summary for anonymous).
    assert len(cursor.executed) == 1


async def test_list_signals_with_user_emits_unread_count() -> None:
    """For an authenticated user, the service issues a main SELECT plus
    an unread-count SELECT, and the items carry the user's
    read/executed flags.
    """
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _row(signal_id="sig-1", is_read=True, is_executed=False),
            _row(signal_id="sig-2", is_read=False, is_executed=False),
        ]
    )
    cursor.push_one({"cnt": 3})
    conn = _FakeConn(cursor)

    items, total, unread = await list_signals(
        conn,  # type: ignore[arg-type]
        user_id="u-1",
        strategy_id=None,
        strategy_ids=None,
        signal_type=None,
        action=None,
        asset_class=None,
        is_read=None,
        confidence_min=None,
        start_date=None,
        end_date=None,
        page=_Page(),
    )

    assert total == 1
    assert unread == 3
    assert items[0]["is_read"] is True
    assert items[1]["is_read"] is False
    # Main SELECT + unread summary SELECT.
    assert len(cursor.executed) == 2
    # The unread query receives a tuple param (user_id).
    unread_sql, unread_params = cursor.executed[1]
    assert "user_signal_reads" in unread_sql
    assert "WHERE s.status" in unread_sql
    assert unread_params == ("u-1",)


async def test_list_signals_filters_by_strategy_id() -> None:
    """`strategy_id` flows into the `codes` ANY() filter on the main
    SELECT — the service accepts a single code here even though the
    param name is plural.
    """
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_signals(
        conn,  # type: ignore[arg-type]
        user_id=None,
        strategy_id="STR_FUT_001",
        strategy_ids=None,
        signal_type=None,
        action=None,
        asset_class=None,
        is_read=None,
        confidence_min=None,
        start_date=None,
        end_date=None,
        page=_Page(),
    )

    main_sql, main_params = cursor.executed[0]
    assert "st.strategy_code = ANY(%(codes)s)" in main_sql
    assert main_params["codes"] == ["STR_FUT_001"]


async def test_list_signals_combines_strategy_filters() -> None:
    """`strategy_id` and `strategy_ids` are merged into a single
    `codes` array — the caller can pass either or both.
    """
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_signals(
        conn,  # type: ignore[arg-type]
        user_id=None,
        strategy_id="STR_FUT_001",
        strategy_ids=["STR_FUT_002", "STR_FUT_003"],
        signal_type=None,
        action=None,
        asset_class=None,
        is_read=None,
        confidence_min=None,
        start_date=None,
        end_date=None,
        page=_Page(),
    )

    main_params = cursor.executed[0][1]
    assert main_params["codes"] == ["STR_FUT_001", "STR_FUT_002", "STR_FUT_003"]


async def test_list_signals_filters_in_query() -> None:
    """signal_type/action/asset_class/confidence_min translate to
    equality or >=-compare WHERE clauses.
    """
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_signals(
        conn,  # type: ignore[arg-type]
        user_id="u-1",
        strategy_id=None,
        strategy_ids=None,
        signal_type="entry",
        action="buy",
        asset_class="futures",
        is_read=None,
        confidence_min=0.7,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
        page=_Page(),
    )

    main_sql, main_params = cursor.executed[0]
    assert "s.type = %(stype)s" in main_sql
    assert "s.action = %(action)s" in main_sql
    assert "st.asset_class = %(asset_class)s" in main_sql
    assert "s.confidence >= %(cmin)s" in main_sql
    assert "s.published_at >= %(start)s" in main_sql
    assert "< (%(end)s::date + INTERVAL '1 day')" in main_sql
    assert main_params["stype"] == "entry"
    assert main_params["action"] == "buy"
    assert main_params["asset_class"] == "futures"
    assert main_params["cmin"] == 0.7
    assert main_params["start"] == date(2026, 5, 1)
    assert main_params["end"] == date(2026, 5, 31)


async def test_list_signals_is_read_filter_requires_user() -> None:
    """`is_read` is silently dropped when `user_id=None` — the service
    can't filter on a join that doesn't exist.
    """
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_signals(
        conn,  # type: ignore[arg-type]
        user_id=None,
        strategy_id=None,
        strategy_ids=None,
        signal_type=None,
        action=None,
        asset_class=None,
        is_read=True,  # ignored for anonymous
        confidence_min=None,
        start_date=None,
        end_date=None,
        page=_Page(),
    )

    main_sql = cursor.executed[0][0]
    # No user JOIN emitted.
    assert "user_signal_reads" not in main_sql
    assert "usr.user_id IS NOT NULL" not in main_sql


async def test_list_signals_serializes_fields_correctly() -> None:
    """Output dict has the public schema (camelCase keys, ISO datetime
    strings, no Decimal types).
    """
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _row(
                signal_id="sig-1",
                trigger_price=3500.0,
                target_price=3600.0,
                stop_loss_price=3450.0,
                confidence=0.85,
            )
        ]
    )
    conn = _FakeConn(cursor)

    items, _, _ = await list_signals(
        conn,  # type: ignore[arg-type]
        user_id=None,
        strategy_id=None,
        strategy_ids=None,
        signal_type=None,
        action=None,
        asset_class=None,
        is_read=None,
        confidence_min=None,
        start_date=None,
        end_date=None,
        page=_Page(),
    )

    item = items[0]
    assert item["id"] == "sig-1"
    assert item["strategy"] == {"id": "STR_FUT_001", "name": "Fut 001"}
    assert item["trigger_price"] == 3500.0
    assert item["target_price"] == 3600.0
    assert item["stop_loss_price"] == 3450.0
    assert item["confidence"] == 0.85
    # Datetime serialized to ISO string.
    assert item["trigger_time"] == "2026-05-01T09:30:00+00:00"


async def test_list_signals_defaults_direction_to_long() -> None:
    """A row with `direction=None` surfaces as "long" (the safe
    default for the dashboard).
    """
    cursor = _FakeCursor()
    cursor.set_rows([_row(direction=None)])
    conn = _FakeConn(cursor)

    items, _, _ = await list_signals(
        conn,  # type: ignore[arg-type]
        user_id=None,
        strategy_id=None,
        strategy_ids=None,
        signal_type=None,
        action=None,
        asset_class=None,
        is_read=None,
        confidence_min=None,
        start_date=None,
        end_date=None,
        page=_Page(),
    )

    assert items[0]["direction"] == "long"


# ---------------------------------------------------------------------------
# unread_summary
# ---------------------------------------------------------------------------


async def test_unread_summary_anonymous_returns_zero_structure() -> None:
    """An anonymous viewer sees all-zero counts and no SQL is issued."""
    cursor = _FakeCursor()
    conn = _FakeConn(cursor)

    result = await unread_summary(conn, user_id=None)  # type: ignore[arg-type]

    assert result == {
        "total_unread": 0,
        "by_strategy": [],
        "by_urgency": {"critical": 0, "high": 0, "normal": 0, "low": 0},
    }
    assert cursor.executed == []


async def test_unread_summary_aggregates_three_queries() -> None:
    """For a user, 3 SELECTs run: total, by-strategy, by-urgency.
    The output merges by-urgency buckets into the canonical shape.
    """
    cursor = _FakeCursor()
    cursor.push_one({"cnt": 5})  # total
    cursor.set_rows(
        [
            {
                "strategy_code": "STR_FUT_001",
                "strategy_name": "Fut 001",
                "unread_count": 3,
                "latest": datetime(2026, 5, 1, 9, 30, tzinfo=timezone.utc),
            },
            {
                "strategy_code": "STR_FUT_002",
                "strategy_name": "Fut 002",
                "unread_count": 2,
                "latest": datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
            },
        ]
    )
    cursor.set_rows(
        [
            {"urgency": "critical", "cnt": 1},
            {"urgency": "high", "cnt": 4},
        ]
    )
    conn = _FakeConn(cursor)

    result = await unread_summary(conn, user_id="u-1")  # type: ignore[arg-type]

    assert result["total_unread"] == 5
    assert result["by_urgency"] == {
        "critical": 1,
        "high": 4,
        "normal": 0,
        "low": 0,
    }
    assert len(result["by_strategy"]) == 2
    assert result["by_strategy"][0]["strategy_id"] == "STR_FUT_001"
    assert result["by_strategy"][0]["unread_count"] == 3
    assert result["by_strategy"][0]["latest_signal_time"] == "2026-05-01T09:30:00+00:00"
    # 3 SELECTs, all parametrized with user_id.
    assert len(cursor.executed) == 3
    for _, params in cursor.executed:
        assert params == ("u-1",)


async def test_unread_summary_handles_unknown_urgency_buckets() -> None:
    """A new urgency bucket (e.g. "emergency") doesn't crash — it's
    simply dropped from the canonical output (which has 4 hard-coded
    buckets).
    """
    cursor = _FakeCursor()
    cursor.push_one({"cnt": 2})
    cursor.set_rows([])
    cursor.set_rows([{"urgency": "emergency", "cnt": 2}])
    conn = _FakeConn(cursor)

    result = await unread_summary(conn, user_id="u-1")  # type: ignore[arg-type]

    assert result["by_urgency"] == {
        "critical": 0,
        "high": 0,
        "normal": 0,
        "low": 0,
    }


# ---------------------------------------------------------------------------
# mark_read
# ---------------------------------------------------------------------------


async def test_mark_read_returns_remaining_unread() -> None:
    """`mark_read` UPSERTs the read row, then counts remaining unread
    for that user. Both queries run; `commit()` is awaited.
    """
    cursor = _FakeCursor()
    cursor.push_one({"read_at": datetime(2026, 5, 1, 9, 30, tzinfo=timezone.utc)})
    cursor.push_one({"cnt": 7})
    conn = _FakeConn(cursor)

    result = await mark_read(
        conn,  # type: ignore[arg-type]
        user_id="u-1",
        signal_id="sig-uuid-1",
        signal_code="SIG_001",
    )

    assert result == {
        "signal_id": "SIG_001",
        "is_read": True,
        "read_at": "2026-05-01T09:30:00+00:00",
        "remaining_unread": 7,
    }
    # 2 SELECTs (UPSERTs go through psycopg's execute path) + commit.
    assert len(cursor.executed) == 2
    upsert_sql, upsert_params = cursor.executed[0]
    assert "INSERT INTO user_signal_reads" in upsert_sql
    assert "ON CONFLICT (user_id, signal_id) DO UPDATE" in upsert_sql
    assert upsert_params == ("u-1", "sig-uuid-1")
    # The remaining-count SELECT.
    count_sql, count_params = cursor.executed[1]
    assert "user_signal_reads" in count_sql
    assert "s.status = 'active'" in count_sql
    assert count_params == ("u-1",)
    assert conn.commits == 1


async def test_mark_read_idempotent_on_repeat_call() -> None:
    """The UPSERT has `ON CONFLICT ... DO UPDATE SET read_at =
    COALESCE(existing.read_at, EXCLUDED.read_at)` — re-marking a
    signal does not regress the original read time. The test asserts
    the SQL contains the COALESCE guard so that this guarantee is
    preserved by future edits.
    """
    cursor = _FakeCursor()
    cursor.push_one({"read_at": datetime(2026, 5, 1, 9, 30, tzinfo=timezone.utc)})
    cursor.push_one({"cnt": 0})
    conn = _FakeConn(cursor)

    await mark_read(
        conn,  # type: ignore[arg-type]
        user_id="u-1",
        signal_id="sig-uuid-1",
        signal_code="SIG_001",
    )

    upsert_sql = cursor.executed[0][0]
    assert "COALESCE(user_signal_reads.read_at, EXCLUDED.read_at)" in upsert_sql
