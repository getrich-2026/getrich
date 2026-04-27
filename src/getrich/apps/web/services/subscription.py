"""策略订阅业务逻辑。

下单 → 创建 order(pending) + order_items + user_strategy_subscriptions(pending_payment)。
取消 → 标记 status=cancelled，access 持续到 expire_date。
查询 → 返回当前用户最有效的一条订阅 + 策略定价。
"""

from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from getrich.apps.web.errors import BadRequest, NotFound


if TYPE_CHECKING:
    from psycopg import AsyncConnection

    from getrich.apps.web.schemas.subscription import SubscribeIn, UnsubscribeIn


_TZ_SH = ZoneInfo("Asia/Shanghai")
_PAYMENT_QR_TTL_MIN = 30  # 支付二维码 / 支付链接的过期时间


# ---------------------------------------------------------------- subscribe

async def subscribe(
    db: AsyncConnection,
    *,
    user_id: str,
    strategy_code: str,
    body: SubscribeIn,
) -> dict[str, Any]:
    """POST /strategies/{strategy_code}/subscribe"""
    async with db.cursor() as cur:
        # 1. 取策略与价格
        await cur.execute(
            """
            SELECT id, name, subscription_monthly, subscription_yearly
            FROM strategies WHERE strategy_code = %s
            """,
            (strategy_code,),
        )
        strat = await cur.fetchone()
        if strat is None:
            raise NotFound(f"strategy not found: {strategy_code}")

        unit_price = strat["subscription_monthly"] if body.plan_type == "monthly" \
            else strat["subscription_yearly"]
        if unit_price is None or unit_price <= 0:
            raise BadRequest(f"strategy {strategy_code} does not support {body.plan_type} plan")

        # 2. 检查是否已有 active 订阅
        await cur.execute(
            """
            SELECT id FROM user_strategy_subscriptions
            WHERE user_id = %s AND strategy_id = %s AND status = 'active'
              AND expire_date >= CURRENT_DATE
            """,
            (user_id, strat["id"]),
        )
        if await cur.fetchone():
            raise BadRequest("already subscribed and active")

        # 3. 创建 order
        now = datetime.now(_TZ_SH)
        order_no = _gen_order_no(now)
        await cur.execute(
            """
            INSERT INTO orders (order_no, user_id, subtotal, total, currency,
                                payment_source, status, expire_at)
            VALUES (%s, %s, %s, %s, 'CNY', %s, 'pending', %s)
            RETURNING id
            """,
            (
                order_no, user_id,
                unit_price, unit_price,
                body.payment_source,
                now + timedelta(minutes=_PAYMENT_QR_TTL_MIN),
            ),
        )
        order_id = (await cur.fetchone())["id"]

        # 4. order_items
        plan_days = 30 if body.plan_type == "monthly" else 365
        await cur.execute(
            """
            INSERT INTO order_items (order_id, item_type, item_id, item_name,
                                     unit_price, quantity, subtotal,
                                     plan_type, duration_days, meta)
            VALUES (%s, 'strategy_subscription', %s, %s, %s, 1, %s, %s, %s, %s)
            """,
            (
                order_id, strat["id"], strat["name"],
                unit_price, unit_price,
                body.plan_type, plan_days,
                _json_meta({"strategy_code": strategy_code, "plan": body.plan_type}),
            ),
        )

        # 5. user_strategy_subscriptions
        start = date.today()
        expire = start + timedelta(days=plan_days)
        await cur.execute(
            """
            INSERT INTO user_strategy_subscriptions
                (user_id, strategy_id, plan_type, status, auto_renew,
                 start_date, expire_date, source_order_id)
            VALUES (%s, %s, %s, 'pending_payment', %s, %s, %s, %s)
            RETURNING id
            """,
            (
                user_id, strat["id"], body.plan_type, body.auto_renew,
                start, expire, order_id,
            ),
        )
        sub_id = (await cur.fetchone())["id"]

        await db.commit()

    return {
        "subscription_id": str(sub_id),
        "status": "pending_payment",
        "plan_type": body.plan_type,
        "start_date": start.isoformat(),
        "expire_date": expire.isoformat(),
        "payment": {
            "order_id": order_no,
            "amount": float(unit_price),
            "payment_source": body.payment_source,
            "expire_time": (now + timedelta(minutes=_PAYMENT_QR_TTL_MIN)).isoformat(),
        },
    }


# ---------------------------------------------------------------- unsubscribe

async def unsubscribe(
    db: AsyncConnection,
    *,
    user_id: str,
    strategy_code: str,
    body: UnsubscribeIn,
) -> dict[str, Any]:
    """POST /strategies/{strategy_code}/unsubscribe"""
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT id FROM strategies WHERE strategy_code = %s",
            (strategy_code,),
        )
        strat = await cur.fetchone()
        if strat is None:
            raise NotFound(f"strategy not found: {strategy_code}")

        # 找当前 active 订阅
        await cur.execute(
            """
            SELECT id, expire_date FROM user_strategy_subscriptions
            WHERE user_id = %s AND strategy_id = %s AND status = 'active'
              AND expire_date >= CURRENT_DATE
            ORDER BY expire_date DESC
            LIMIT 1
            """,
            (user_id, strat["id"]),
        )
        row = await cur.fetchone()
        if row is None:
            raise NotFound("no active subscription to cancel")

        await cur.execute(
            """
            UPDATE user_strategy_subscriptions
               SET status = 'cancelled',
                   auto_renew = FALSE,
                   cancelled_at = NOW(),
                   cancel_reason = %s,
                   updated_at = NOW()
             WHERE id = %s
            """,
            (body.reason, row["id"]),
        )
        await db.commit()

    return {
        "strategy_id": strategy_code,
        "status": "cancelled",
        "access_until": row["expire_date"].isoformat(),
    }


# ---------------------------------------------------------------- get status

async def get_subscription_status(
    db: AsyncConnection,
    *,
    user_id: str | None,
    strategy_code: str,
) -> dict[str, Any]:
    """GET /strategies/{strategy_code}/subscription"""
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT id, subscription_monthly, subscription_yearly
            FROM strategies WHERE strategy_code = %s
            """,
            (strategy_code,),
        )
        strat = await cur.fetchone()
        if strat is None:
            raise NotFound(f"strategy not found: {strategy_code}")

        sub = None
        if user_id:
            await cur.execute(
                """
                SELECT id, plan_type, status, start_date, expire_date, auto_renew
                FROM user_strategy_subscriptions
                WHERE user_id = %s AND strategy_id = %s
                ORDER BY
                    CASE status
                        WHEN 'active' THEN 0
                        WHEN 'pending_payment' THEN 1
                        ELSE 2
                    END,
                    expire_date DESC
                LIMIT 1
                """,
                (user_id, strat["id"]),
            )
            sub = await cur.fetchone()

    is_active = bool(
        sub
        and sub["status"] == "active"
        and sub["expire_date"] >= date.today()
    )
    return {
        "is_subscribed": is_active,
        "subscription_id": str(sub["id"]) if sub else None,
        "status": sub["status"] if sub else None,
        "plan_type": sub["plan_type"] if sub else None,
        "start_date": sub["start_date"].isoformat() if sub else None,
        "expire_date": sub["expire_date"].isoformat() if sub else None,
        "auto_renew": sub["auto_renew"] if sub else None,
        "subscription_price": {
            "monthly": float(strat["subscription_monthly"] or 0),
            "yearly": float(strat["subscription_yearly"] or 0),
        },
    }


# ---------------------------------------------------------------- helpers

def _gen_order_no(now: datetime) -> str:
    return f"ORD_{now.strftime('%Y%m%d')}_{secrets.token_hex(4).upper()}"


def _json_meta(d: dict[str, Any]) -> str:
    import json
    return json.dumps(d, ensure_ascii=False)
