"""Tests for the order service.

`services.order` is the read-only order-history view used by
`GET /v1/user/orders`. The function joins `orders` to
`order_items` + `strategies` to produce a denormalized list where
each order has its line items inlined. The two cases that need
explicit coverage are:

- **no rows** → must short-circuit before the items `SELECT`
  (a `WHERE oi.order_id = ANY(...)` against an empty list would
  return no rows, but the production code chooses the explicit
  early return to avoid a wasted roundtrip).
- **multi-item join** → items must be grouped by `order_id` and
  each order's output dict has the items inlined under `items`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from gr_api.services.order import list_orders


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Mock async cursor.

    `fetchall` returns the next pre-loaded list of rows (FIFO);
    `fetchone` is not used by this service."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, Any] | tuple]] = []
        self._fetchall_q: list[list[dict[str, Any]]] = []
        self._call_idx: int = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def execute(self, sql, params=None):
        self.executed.append((sql.strip(), params))
        self._call_idx += 1

    async def fetchall(self) -> list[dict[str, Any]]:
        if self._fetchall_q:
            return self._fetchall_q.pop(0)
        return []

    async def fetchone(self):  # pragma: no cover — service doesn't call
        return None

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        """Queue a result for the NEXT `fetchall` call."""
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _order_row(
    *,
    id: str = "order-uuid-1",
    order_no: str = "ORD_20260601_AAAAAAAA",
    status: str = "paid",
    total: float = 99.0,
    payment_source: str = "wechat",
    created_at: datetime | None = None,
    paid_at: datetime | None = None,
    total_count: int = 1,
) -> dict[str, Any]:
    return {
        "id": id,
        "order_no": order_no,
        "status": status,
        "total": total,
        "payment_source": payment_source,
        "created_at": created_at or datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
        "paid_at": paid_at,
        "_total": total_count,
    }


def _item_row(
    *,
    order_id: str = "order-uuid-1",
    item_type: str = "strategy_subscription",
    item_name: str = "Fut 001 monthly",
    unit_price: float = 99.0,
    subtotal: float = 99.0,
    plan_type: str = "monthly",
    duration_days: int = 30,
    strategy_code: str | None = "STR_FUT_001",
) -> dict[str, Any]:
    return {
        "order_id": order_id,
        "item_type": item_type,
        "item_name": item_name,
        "unit_price": unit_price,
        "subtotal": subtotal,
        "plan_type": plan_type,
        "duration_days": duration_days,
        "meta": None,
        "strategy_code": strategy_code,
    }


# ---------------------------------------------------------------------------
# list_orders
# ---------------------------------------------------------------------------


async def test_list_orders_returns_empty_short_circuit() -> None:
    """When the main SELECT returns no rows, the service MUST return
    ([], 0) immediately and NOT issue the items `SELECT` — a `WHERE
    oi.order_id = ANY(NULL/empty)` roundtrip is wasted work and
    would also be confusing to read in a trace.
    """
    cursor = _FakeCursor()
    cursor.set_rows([])  # main SELECT → no orders
    conn = _FakeConn(cursor)

    items, total = await list_orders(
        conn,  # type: ignore[arg-type]
        user_id="u-1",
        status=None,
        page=_Page(),
    )

    assert items == []
    assert total == 0
    # Only the main SELECT ran; the items join was skipped.
    assert len(cursor.executed) == 1


async def test_list_orders_user_id_always_in_where_clause() -> None:
    """The `user_id` filter is mandatory — even if `status` is None
    the WHERE must still scope to the calling user. This guards
    against an accidental refactor that drops the conds loop and
    leaves a tenant-bleed bug.
    """
    cursor = _FakeCursor()
    cursor.set_rows([_order_row()])
    cursor.set_rows([_item_row()])
    conn = _FakeConn(cursor)

    await list_orders(
        conn,  # type: ignore[arg-type]
        user_id="u-attacker",
        status=None,
        page=_Page(),
    )

    main_sql, main_params = cursor.executed[0]
    assert "user_id = %(uid)s" in main_sql
    assert main_params["uid"] == "u-attacker"
    # No status filter was added.
    assert "status = %(status)s" not in main_sql
    assert "status" not in main_params


async def test_list_orders_status_filter_applied_when_specific() -> None:
    cursor = _FakeCursor()
    cursor.set_rows([_order_row(status="paid")])
    cursor.set_rows([_item_row()])
    conn = _FakeConn(cursor)

    await list_orders(
        conn,  # type: ignore[arg-type]
        user_id="u-1",
        status="paid",
        page=_Page(),
    )

    main_sql, main_params = cursor.executed[0]
    assert "status = %(status)s" in main_sql
    assert main_params["status"] == "paid"


async def test_list_orders_status_all_passes_through_unchecked() -> None:
    """`status="all"` is the frontend's "no filter" sentinel. The
    service treats it as no filter (the conds loop skips it via the
    `status != "all"` guard). This is the contract: the route's
    Pydantic `pattern=` accepts "all", the service does not add it
    to the WHERE.
    """
    cursor = _FakeCursor()
    cursor.set_rows([_order_row()])
    cursor.set_rows([_item_row()])
    conn = _FakeConn(cursor)

    await list_orders(
        conn,  # type: ignore[arg-type]
        user_id="u-1",
        status="all",
        page=_Page(),
    )

    main_sql, main_params = cursor.executed[0]
    assert "status = %(status)s" not in main_sql
    assert "status" not in main_params


async def test_list_orders_pagination_params() -> None:
    cursor = _FakeCursor()
    cursor.set_rows([_order_row()])
    cursor.set_rows([_item_row()])
    conn = _FakeConn(cursor)

    await list_orders(
        conn,  # type: ignore[arg-type]
        user_id="u-1",
        status=None,
        page=_Page(limit=50, offset=100),
    )

    main_params = cursor.executed[0][1]
    assert main_params["limit"] == 50
    assert main_params["offset"] == 100


async def test_list_orders_joins_items_per_order() -> None:
    """Two orders, each with its own line items, must produce a list
    where each order's `items` field contains ONLY its own items
    (not all items). This catches an off-by-one in the items
    grouping loop.
    """
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _order_row(
                id="order-uuid-1",
                order_no="ORD_001",
                total_count=2,
            ),
            _order_row(
                id="order-uuid-2",
                order_no="ORD_002",
                total_count=2,
            ),
        ]
    )
    cursor.set_rows(
        [
            _item_row(order_id="order-uuid-1", item_name="Item 1A"),
            _item_row(order_id="order-uuid-1", item_name="Item 1B"),
            _item_row(order_id="order-uuid-2", item_name="Item 2A"),
        ]
    )
    conn = _FakeConn(cursor)

    items, total = await list_orders(
        conn,  # type: ignore[arg-type]
        user_id="u-1",
        status=None,
        page=_Page(),
    )

    assert total == 2  # _total from first row, all rows share it
    assert len(items) == 2
    # Order 1 has 2 items
    assert items[0]["order_id"] == "ORD_001"
    assert [it["item_name"] for it in items[0]["items"]] == ["Item 1A", "Item 1B"]
    # Order 2 has 1 item
    assert items[1]["order_id"] == "ORD_002"
    assert [it["item_name"] for it in items[1]["items"]] == ["Item 2A"]


async def test_list_orders_item_with_null_strategy_code() -> None:
    """An item whose `item_type` is not a strategy type (e.g. a
    future non-strategy add-on) gets `strategy_code=None` from the
    LEFT JOIN. The output `item_id` should be an empty string, not
    `None` — JS clients prefer stable string fields.
    """
    cursor = _FakeCursor()
    cursor.set_rows([_order_row()])
    cursor.set_rows(
        [
            _item_row(
                item_type="platform_fee",
                strategy_code=None,
            )
        ]
    )
    conn = _FakeConn(cursor)

    items, _ = await list_orders(
        conn,  # type: ignore[arg-type]
        user_id="u-1",
        status=None,
        page=_Page(),
    )

    assert items[0]["items"][0]["item_id"] == ""


async def test_list_orders_serializes_datetimes_to_iso() -> None:
    """`created_at` is required (NOT NULL in the schema) so it must
    always serialize to an ISO string. `paid_at` is optional and
    stays `None` for unpaid orders.
    """
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _order_row(
                created_at=datetime(2026, 6, 1, 9, 30, tzinfo=timezone.utc),
                paid_at=datetime(2026, 6, 1, 9, 31, tzinfo=timezone.utc),
            )
        ]
    )
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    items, _ = await list_orders(
        conn,  # type: ignore[arg-type]
        user_id="u-1",
        status=None,
        page=_Page(),
    )

    assert items[0]["created_at"] == "2026-06-01T09:30:00+00:00"
    assert items[0]["paid_at"] == "2026-06-01T09:31:00+00:00"


async def test_list_orders_paid_at_none_stays_none() -> None:
    """An unpaid order's `paid_at` must remain `None` (not the string
    "None", not an empty string) so the frontend can use a simple
    `null`-check to decide whether to render the "Mark paid" CTA.
    """
    cursor = _FakeCursor()
    cursor.set_rows([_order_row(status="pending", paid_at=None)])
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    items, _ = await list_orders(
        conn,  # type: ignore[arg-type]
        user_id="u-1",
        status=None,
        page=_Page(),
    )

    assert items[0]["paid_at"] is None


async def test_list_orders_items_select_filters_to_order_ids() -> None:
    """The items SELECT must scope to the IDs from the main query
    via `WHERE oi.order_id = ANY(%s)` so it doesn't scan the entire
    `order_items` table.
    """
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _order_row(id="order-uuid-1"),
            _order_row(id="order-uuid-2"),
        ]
    )
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_orders(
        conn,  # type: ignore[arg-type]
        user_id="u-1",
        status=None,
        page=_Page(),
    )

    items_sql, items_params = cursor.executed[1]
    assert "WHERE oi.order_id = ANY(%s)" in items_sql
    # The ANY() array is the IDs from the main query, in order.
    assert items_params == (["order-uuid-1", "order-uuid-2"],)
