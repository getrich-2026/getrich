"""订单查询业务逻辑。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from psycopg import AsyncConnection

    from getrich.apps.web.pagination import PageParams


async def list_orders(
    db: AsyncConnection,
    *,
    user_id: str,
    status: str | None,
    page: PageParams,
) -> tuple[list[dict[str, Any]], int]:
    """GET /user/orders"""
    conds = ["user_id = %(uid)s"]
    params: dict[str, Any] = {"uid": user_id, "limit": page.limit, "offset": page.offset}
    if status and status != "all":
        conds.append("status = %(status)s")
        params["status"] = status
    where_sql = " AND ".join(conds)

    async with db.cursor() as cur:
        await cur.execute(
            f"""
            SELECT id, order_no, status, total, payment_source, created_at, paid_at,
                   COUNT(*) OVER() AS _total
            FROM orders
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            params,
        )
        order_rows = await cur.fetchall()

        if not order_rows:
            return [], 0

        order_ids = [r["id"] for r in order_rows]
        await cur.execute(
            """
            SELECT oi.order_id, oi.item_type, oi.item_name, oi.unit_price,
                   oi.subtotal, oi.plan_type, oi.duration_days, oi.meta,
                   s.strategy_code AS strategy_code
            FROM order_items oi
            LEFT JOIN strategies s ON s.id = oi.item_id
                                  AND oi.item_type IN ('strategy_subscription', 'strategy_payg')
            WHERE oi.order_id = ANY(%s)
            """,
            (order_ids,),
        )
        item_rows = await cur.fetchall()

    items_by_order: dict[Any, list[dict[str, Any]]] = {}
    for ir in item_rows:
        oid = ir["order_id"]
        items_by_order.setdefault(oid, []).append({
            "item_type": ir["item_type"],
            "item_id": ir["strategy_code"] or "",
            "item_name": ir["item_name"],
            "plan_type": ir["plan_type"],
            "amount": float(ir["subtotal"]),
        })

    total = int(order_rows[0]["_total"])
    out = [
        {
            "order_id": r["order_no"],
            "status": r["status"],
            "total_amount": float(r["total"]),
            "payment_source": r["payment_source"],
            "created_at": _dt(r["created_at"]),
            "paid_at": _dt(r["paid_at"]),
            "items": items_by_order.get(r["id"], []),
        }
        for r in order_rows
    ]
    return out, total


def _dt(v: datetime | None) -> str | None:
    if v is None:
        return None
    return v.isoformat()
