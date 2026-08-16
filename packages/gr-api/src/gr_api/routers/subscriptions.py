"""订阅相关路由：subscribe / unsubscribe / status。

挂在 /strategies/{strategy_code} 下，与 strategies router 互不冲突。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from gr_api.deps import get_current_user, get_db, request_id, require_user
from gr_api.response import success
from gr_api.schemas.subscription import SubscribeIn, UnsubscribeIn
from gr_api.services import subscription as svc


if TYPE_CHECKING:
    from psycopg import AsyncConnection


router = APIRouter(tags=["subscriptions"])


@router.post("/strategies/{strategy_code}/subscribe")
async def subscribe(
    strategy_code: str,
    body: SubscribeIn,
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    data = await svc.subscribe(
        db,
        user_id=user_id,
        strategy_code=strategy_code,
        body=body,
    )
    return success(data, rid)


@router.post("/strategies/{strategy_code}/unsubscribe")
async def unsubscribe(
    strategy_code: str,
    body: UnsubscribeIn | None = None,
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    data = await svc.unsubscribe(
        db,
        user_id=user_id,
        strategy_code=strategy_code,
        body=body or UnsubscribeIn(),
    )
    return success(data, rid)


@router.get("/strategies/{strategy_code}/subscription")
async def get_subscription(
    strategy_code: str,
    user_id: str | None = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    data = await svc.get_subscription_status(
        db,
        user_id=user_id,
        strategy_code=strategy_code,
    )
    return success(data, rid)
