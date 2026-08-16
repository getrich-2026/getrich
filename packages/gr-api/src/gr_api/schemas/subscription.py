"""订阅 / 推送设置 / Webhook 的请求体模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------- 订阅


class SubscribeIn(BaseModel):
    plan_type: Literal["monthly", "yearly"]
    payment_source: Literal["wechat", "alipay", "bank", "apple_pay", "stripe"]
    auto_renew: bool = True


class UnsubscribeIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


# ---------------------------------------------------------------- 推送设置

UrgencyLevel = Literal["low", "normal", "high", "critical"]


class ChannelsPatch(BaseModel):
    app_push: bool | None = None
    sms: bool | None = None
    email: bool | None = None
    wechat_service: bool | None = None
    websocket: bool | None = None


class StrategySettingsPatch(BaseModel):
    enabled: bool | None = None
    channels: ChannelsPatch | None = None
    urgency_filter: list[UrgencyLevel] | None = None
    confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    notify_entry_only: bool | None = None


class QuietHoursPatch(BaseModel):
    enabled: bool | None = None
    start: str | None = None
    end: str | None = None


class GlobalSettingsPatch(BaseModel):
    confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    urgency_filter: list[UrgencyLevel] | None = None
    quiet_hours: QuietHoursPatch | None = None
    trading_hours_only: bool | None = None


class GlobalSettingsIn(BaseModel):
    push_enabled: bool | None = None
    channels: ChannelsPatch | None = None
    global_settings: GlobalSettingsPatch | None = None


# ---------------------------------------------------------------- Webhook


class PaymentWebhookIn(BaseModel):
    order_id: str
    payment_ref: str
    status: Literal["success", "failed", "refunded"]
    amount: float = Field(ge=0)
    payment_source: Literal["wechat", "alipay", "bank", "apple_pay", "stripe"]
    paid_at: datetime | None = None
