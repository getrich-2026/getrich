"""用户模块路由：订单列表。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query

from getrich.apps.web.deps import get_db, page_dep, request_id, require_user
from getrich.apps.web.pagination import make_pagination
from getrich.apps.web.response import success
from getrich.apps.web.services import order as svc


if TYPE_CHECKING:
    from psycopg import AsyncConnection

    from getrich.apps.web.pagination import PageParams


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
