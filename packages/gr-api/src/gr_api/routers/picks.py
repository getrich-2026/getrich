"""选股展示模块路由：6 个公开 GET + 1 个管理端 GET。

契约见 ``getrich-design/strategy-signal/api-spec/选股展示模块.openapi.json``。
路由分三组挂载（``main.py`` 里统一加 ``/v1`` 前缀）：

* ``/v1/pick-strategies*`` —— 策略列表 / 详情 / 标的池 / 交易日列表
* ``/v1/picks*``           —— 跨策略汇总 / 个股反查
* ``/v1/admin/pick-batches`` —— 上传批次（``require_admin``）

路由层只做参数校验与响应包壳，SQL 全在 ``services/pick.py``。
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query
from gr_api.deps import get_current_user, get_db, page_dep, request_id, require_admin
from gr_api.pagination import make_page_params, make_pagination
from gr_api.response import success
from gr_api.services import pick as pick_svc


if TYPE_CHECKING:
    from gr_api.pagination import PageParams
    from psycopg import AsyncConnection


strategies_router = APIRouter(prefix="/pick-strategies", tags=["策略模块 - 选股展示"])
picks_router = APIRouter(prefix="/picks", tags=["策略模块 - 选股展示"])
admin_router = APIRouter(prefix="/admin/pick-batches", tags=["策略模块 - 选股导入"])


# ---------------------------------------------------------------- 策略列表


@strategies_router.get("")
async def list_pick_strategies(
    category_id: str | None = None,
    keyword: str | None = None,
    data_state: str = Query("all", pattern=r"^(all|updated|empty|not_updated)$"),
    sort: str = Query("latest_trading_day", pattern=r"^(latest_trading_day|subscribers|newest)$"),
    sort_order: str = Query("desc", pattern=r"^(asc|desc)$"),
    status: str = Query("active", pattern=r"^(active|all)$"),
    page: PageParams = Depends(page_dep),
    user_id: str | None = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    items, total = await pick_svc.list_pick_strategies(
        db,
        user_id=user_id,
        category_id=category_id,
        keyword=keyword,
        data_state=data_state,
        status=status,
        sort=sort,
        sort_order=sort_order,
        page=page,
    )
    return success(
        {
            "list": items,
            "pagination": make_pagination(page, total),
            "order": {"field": sort, "direction": sort_order},
        },
        rid,
    )


# ---------------------------------------------------------------- 策略详情


@strategies_router.get("/{strategy_id}")
async def get_pick_strategy(
    strategy_id: str,
    user_id: str | None = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    data = await pick_svc.get_pick_strategy(db, strategy_ref=strategy_id, user_id=user_id)
    return success(data, rid)


# ---------------------------------------------------------------- 标的池


@strategies_router.get("/{strategy_id}/picks")
async def list_strategy_picks(
    strategy_id: str,
    trading_day: date | None = None,
    sort: str = Query("rank", pattern=r"^(rank|entry_date|symbol)$"),
    page: int = Query(1, ge=1),
    # 标的池通常 20–50 只，前端一般一次取全，所以这里的上限比全局的 100 更宽。
    page_size: int = Query(100, ge=1, le=200),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    page_params = make_page_params(page=page, page_size=page_size, max_page_size=200)
    data = await pick_svc.list_strategy_picks(
        db,
        strategy_ref=strategy_id,
        trading_day=trading_day,
        sort=sort,
        page=page_params,
    )
    total = data.pop("total")
    return success({**data, "pagination": make_pagination(page_params, total)}, rid)


@strategies_router.get("/{strategy_id}/trading-days")
async def list_pick_trading_days(
    strategy_id: str,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(90, ge=1, le=500),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    data = await pick_svc.list_pick_trading_days(
        db,
        strategy_ref=strategy_id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    return success(data, rid)


# ---------------------------------------------------------------- 跨策略汇总


@picks_router.get("/latest")
async def list_latest_picks(
    category_id: str | None = None,
    subscribed_only: bool = False,
    preview_size: int = Query(5, ge=1, le=20),
    page: PageParams = Depends(page_dep),
    user_id: str | None = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    items, total = await pick_svc.list_latest_picks(
        db,
        user_id=user_id,
        category_id=category_id,
        subscribed_only=subscribed_only,
        preview_size=preview_size,
        page=page,
    )
    return success({"list": items, "pagination": make_pagination(page, total)}, rid)


@picks_router.get("/by-symbol/{symbol}")
async def list_picks_by_symbol(
    symbol: str,
    start_date: date | None = None,
    end_date: date | None = None,
    in_pool_only: bool = False,
    page: PageParams = Depends(page_dep),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    data = await pick_svc.list_picks_by_symbol(
        db,
        symbol_full=symbol,
        start_date=start_date,
        end_date=end_date,
        in_pool_only=in_pool_only,
        page=page,
    )
    total = data.pop("total")
    return success({**data, "pagination": make_pagination(page, total)}, rid)


# ---------------------------------------------------------------- 管理端


@admin_router.get("")
async def list_pick_batches(
    strategy_id: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    status: str = Query("active", pattern=r"^(active|superseded|all)$"),
    page: PageParams = Depends(page_dep),
    _admin: str = Depends(require_admin),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    items, total = await pick_svc.list_pick_batches(
        db,
        strategy_ref=strategy_id,
        start_date=start_date,
        end_date=end_date,
        status=status,
        page=page,
    )
    return success({"list": items, "pagination": make_pagination(page, total)}, rid)
