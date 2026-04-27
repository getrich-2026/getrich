"""支付回调业务逻辑：幂等更新 order + 激活订阅。"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import TYPE_CHECKING, Any

from getrich.apps.web.errors import BadRequest, NotFound, Unauthorized


if TYPE_CHECKING:
    from getrich.apps.web.schemas.subscription import PaymentWebhookIn

    from psycopg import AsyncConnection


def verify_signature(raw_body: bytes, signature: str | None) -> None:
    """HMAC-SHA256 验签。

    通过环境变量 PAYMENT_WEBHOOK_SECRET 注入；未设置则跳过验签（开发模式）。
    """
    secret = os.environ.get("PAYMENT_WEBHOOK_SECRET")
    if not secret:
        return
    if not signature:
        raise Unauthorized("missing X-Webhook-Signature header")
    expected = hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise Unauthorized("invalid webhook signature")


async def handle_webhook(
    db: AsyncConnection,
    body: PaymentWebhookIn,
) -> dict[str, Any]:
    """POST /webhooks/payment

    幂等：以 payment_ref 为去重键。
    成功路径：orders.status=paid + 订阅 status=active。
    """
    async with db.cursor() as cur:
        # 1. 幂等：若 payment_ref 已落库且状态已结，直接返回
        await cur.execute(
            "SELECT id, status FROM orders WHERE payment_ref = %s",
            (body.payment_ref,),
        )
        existing = await cur.fetchone()

        # 2. 取目标订单
        await cur.execute(
            "SELECT id, status FROM orders WHERE order_no = %s",
            (body.order_id,),
        )
        order = await cur.fetchone()
        if order is None:
            raise NotFound(f"order not found: {body.order_id}")

        if existing is not None and existing["id"] != order["id"]:
            raise BadRequest("payment_ref already bound to a different order")

        # 已经处理过的：直接 200
        if order["status"] in ("paid", "refunded", "cancelled", "failed"):
            return {"order_id": body.order_id, "processed": True}

        if body.status == "success":
            await cur.execute(
                """
                UPDATE orders
                   SET status = 'paid',
                       payment_ref = %s,
                       payment_source = %s,
                       paid_at = COALESCE(%s, NOW())
                 WHERE id = %s
                """,
                (body.payment_ref, body.payment_source, body.paid_at, order["id"]),
            )
            # 激活该订单关联的订阅（若有）
            await cur.execute(
                """
                UPDATE user_strategy_subscriptions
                   SET status = 'active', updated_at = NOW()
                 WHERE source_order_id = %s
                   AND status = 'pending_payment'
                """,
                (order["id"],),
            )
            # 创建 PayG access_grant（如订单含 strategy_payg）
            await cur.execute(
                """
                INSERT INTO strategy_access_grants
                    (user_id, strategy_id, source_order_id, expires_at)
                SELECT o.user_id, oi.item_id, o.id,
                       CASE
                           WHEN oi.duration_days IS NULL THEN NULL
                           ELSE NOW() + (oi.duration_days || ' days')::INTERVAL
                       END
                FROM orders o
                JOIN order_items oi ON oi.order_id = o.id
                WHERE o.id = %s
                  AND oi.item_type = 'strategy_payg'
                ON CONFLICT (user_id, strategy_id) DO UPDATE SET
                    source_order_id = EXCLUDED.source_order_id,
                    expires_at = EXCLUDED.expires_at
                """,
                (order["id"],),
            )
        elif body.status == "failed":
            await cur.execute(
                "UPDATE orders SET status = 'failed' WHERE id = %s",
                (order["id"],),
            )
        elif body.status == "refunded":
            await cur.execute(
                """
                UPDATE orders
                   SET status = 'refunded',
                       refunded_at = NOW()
                 WHERE id = %s
                """,
                (order["id"],),
            )
            await cur.execute(
                """
                UPDATE user_strategy_subscriptions
                   SET status = 'cancelled', cancelled_at = NOW(), updated_at = NOW()
                 WHERE source_order_id = %s
                """,
                (order["id"],),
            )

        await db.commit()

    return {"order_id": body.order_id, "processed": True}
