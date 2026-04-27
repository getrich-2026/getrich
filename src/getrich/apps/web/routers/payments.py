"""支付回调 Webhook。

幂等：以 payment_ref 去重；HMAC 验签密钥从环境变量 PAYMENT_WEBHOOK_SECRET 取，
未配置时跳过验签（便于本地联调）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Header, Request

from getrich.apps.web.deps import get_db, request_id
from getrich.apps.web.response import success
from getrich.apps.web.schemas.subscription import PaymentWebhookIn
from getrich.apps.web.services import payment as svc


if TYPE_CHECKING:
    from psycopg import AsyncConnection


router = APIRouter(tags=["payments"])


@router.post("/webhooks/payment")
async def payment_webhook(
    request: Request,
    x_webhook_signature: str | None = Header(default=None, alias="X-Webhook-Signature"),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    raw = await request.body()
    svc.verify_signature(raw, x_webhook_signature)
    body = PaymentWebhookIn.model_validate_json(raw)
    data = await svc.handle_webhook(db, body)
    return success(data, rid)
