"""用户模块路由：订单列表。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query
from gr_api.deps import get_db, page_dep, request_id, require_user
from gr_api.pagination import make_pagination
from gr_api.response import success
from gr_api.services import order as svc


if TYPE_CHECKING:
    from gr_api.pagination import PageParams
    from psycopg import AsyncConnection


router = APIRouter(prefix="/user", tags=["user"])


@router.get("/orders")
async def list_orders(
    status: str | None = Query(None, pattern=r"^(pending|paid|cancelled|refunded|failed|all)$"),
    page: PageParams = Depends(page_dep),
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    items, total = await svc.list_orders(db, user_id=user_id, status=status, page=page)
    return success(
        {"list": items, "pagination": make_pagination(page, total)},
        rid,
    )
