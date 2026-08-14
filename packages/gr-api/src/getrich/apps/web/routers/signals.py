"""信号模块路由：5 个接口。

注意路由顺序：/unread-summary 必须在 /{signal_code} 之前注册，
否则 'unread-summary' 会被当作 signal_code 进入解析。
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query

from getrich.apps.web.deps import (
    get_current_user,
    get_db,
    page_dep,
    request_id,
    require_user,
)
from getrich.apps.web.pagination import make_pagination
from getrich.apps.web.response import success
from getrich.apps.web.schemas.signal import ExecuteSignalIn
from getrich.apps.web.services import resolver, signal as signal_svc


if TYPE_CHECKING:
    from psycopg import AsyncConnection

    from getrich.apps.web.pagination import PageParams


router = APIRouter(prefix="/signals", tags=["signals"])


# ---------------------------------------------------------------- list

@router.get("")
async def list_signals(
    strategy_id: str | None = None,
    strategy_ids: list[str] | None = Query(default=None),
    signal_type: str | None = Query(None, pattern=r"^(entry|exit|adjust|alert)$"),
    action: str | None = Query(None, pattern=r"^(buy|sell|hold|close)$"),
    asset_class: str | None = None,
    is_read: bool | None = None,
    confidence_min: float | None = Query(None, ge=0.0, le=1.0),
    start_date: date | None = None,
    end_date: date | None = None,
    page: PageParams = Depends(page_dep),
    user_id: str | None = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    items, total, unread = await signal_svc.list_signals(
        db,
        user_id=user_id,
        strategy_id=strategy_id,
        strategy_ids=strategy_ids,
        signal_type=signal_type,
        action=action,
        asset_class=asset_class,
        is_read=is_read,
        confidence_min=confidence_min,
        start_date=start_date,
        end_date=end_date,
        page=page,
    )
    return success(
        {
            "list": items,
            "pagination": make_pagination(page, total),
            "unread_count": unread,
        },
        rid,
    )


# ---------------------------------------------------------------- unread summary

@router.get("/unread-summary")
async def unread_summary(
    user_id: str | None = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    data = await signal_svc.unread_summary(db, user_id=user_id)
    return success(data, rid)


# ---------------------------------------------------------------- detail

@router.get("/{signal_code}")
async def get_signal_detail(
    signal_code: str,
    user_id: str | None = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    sid = await resolver.signal_code_to_id(db, signal_code)
    data = await signal_svc.get_signal_detail(
        db, signal_id=sid, signal_code=signal_code, user_id=user_id,
    )
    return success(data, rid)


# ---------------------------------------------------------------- mark read

@router.post("/{signal_code}/read")
async def mark_read(
    signal_code: str,
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    sid = await resolver.signal_code_to_id(db, signal_code)
    data = await signal_svc.mark_read(
        db, user_id=user_id, signal_id=sid, signal_code=signal_code,
    )
    return success(data, rid)


# ---------------------------------------------------------------- execute

@router.post("/{signal_code}/execute")
async def record_execute(
    signal_code: str,
    body: ExecuteSignalIn,
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    sid = await resolver.signal_code_to_id(db, signal_code)
    data = await signal_svc.record_execute(
        db, user_id=user_id, signal_id=sid, signal_code=signal_code, body=body,
    )
    return success(data, rid)
