"""推送设置路由：策略级 + 用户全局。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from gr_api.deps import get_db, request_id, require_user
from gr_api.response import success
from gr_api.schemas.subscription import (
    GlobalSettingsIn,
    StrategySettingsPatch,
)
from gr_api.services import signal_settings as svc


if TYPE_CHECKING:
    from psycopg import AsyncConnection


router = APIRouter(tags=["signal-settings"])


# ---------------------------------------------------------------- 用户全局


@router.get("/user/signal-settings")
async def get_user_settings(
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    data = await svc.get_global_settings(db, user_id=user_id)
    return success(data, rid)


@router.put("/user/signal-settings")
async def update_user_settings(
    body: GlobalSettingsIn,
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    data = await svc.update_global_settings(db, user_id=user_id, body=body)
    return success(data, rid)


# ---------------------------------------------------------------- 策略覆盖


@router.get("/strategies/{strategy_code}/signal-settings")
async def get_strategy_signal_settings(
    strategy_code: str,
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    data = await svc.get_strategy_settings(
        db,
        user_id=user_id,
        strategy_code=strategy_code,
    )
    return success(data, rid)


@router.put("/strategies/{strategy_code}/signal-settings")
async def update_strategy_signal_settings(
    strategy_code: str,
    body: StrategySettingsPatch,
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    data = await svc.update_strategy_settings(
        db,
        user_id=user_id,
        strategy_code=strategy_code,
        body=body,
    )
    return success(data, rid)
