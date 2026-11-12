"""支付回调 Webhook。

幂等：以 payment_ref 去重；HMAC 验签密钥从环境变量 PAYMENT_WEBHOOK_SECRET 取，
未配置时拒绝回调。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Header, Request
from gr_api.config import ApiSettings
from gr_api.deps import get_db, get_settings, request_id
from gr_api.errors import Unauthorized
from gr_api.response import success
from gr_api.schemas.subscription import PaymentWebhookIn
from gr_api.services import payment as svc


if TYPE_CHECKING:
    from gr_data.db import DictConnection


router = APIRouter(tags=["payments"])


def require_webhook_config(settings: ApiSettings = Depends(get_settings)) -> None:
    """缺少密钥时在获取数据库连接前拒绝回调。"""
    if not settings.payment_webhook_secret.strip():
        raise Unauthorized("payment webhook is not configured", http_status=503)


@router.post("/webhooks/payment", dependencies=[Depends(require_webhook_config)])
async def payment_webhook(
    request: Request,
    x_webhook_signature: str | None = Header(default=None, alias="X-Webhook-Signature"),
    db: DictConnection = Depends(get_db),
    rid: str = Depends(request_id),
    settings: ApiSettings = Depends(get_settings),
):
    raw = await request.body()
    svc.verify_signature(raw, x_webhook_signature, secret=settings.payment_webhook_secret)
    body = PaymentWebhookIn.model_validate_json(raw)
    data = await svc.handle_webhook(db, body)
    return success(data, rid)
