"""策略模块路由：8 个 GET 接口 + 1 个 PUT 接口。"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Query
from gr_api.deps import get_current_user, get_db, page_dep, request_id, require_user
from gr_api.pagination import make_pagination
from gr_api.response import success
from gr_api.services import resolver, strategy as strategy_svc
from pydantic import BaseModel, Field


if TYPE_CHECKING:
    from gr_api.pagination import PageParams
    from psycopg import AsyncConnection


router = APIRouter(prefix="/strategies", tags=["strategies"])


# ---------------------------------------------------------------- categories


@router.get("/categories")
async def list_categories(
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    rows = await strategy_svc.list_categories(db)
    return success({"categories": rows}, rid)


# ---------------------------------------------------------------- list


@router.get("")
async def list_strategies(
    category_id: str | None = None,
    asset_class: str | None = None,
    risk_level: str | None = None,
    market: str | None = None,
    keyword: str | None = None,
    status: str | None = None,
    sort: str = Query(
        "newest",
        pattern=r"^(sharpe|annualized_return|max_drawdown|subscribers|newest)$",
    ),
    sort_order: str = Query("desc", pattern=r"^(asc|desc)$"),
    page: PageParams = Depends(page_dep),
    user_id: str | None = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    items, total = await strategy_svc.list_strategies(
        db,
        user_id=user_id,
        category_id=category_id,
        asset_class=asset_class,
        risk_level=risk_level,
        market=market,
        keyword=keyword,
        status=status,
        sort=sort,
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


# ---------------------------------------------------------------- detail


@router.get("/{strategy_code}")
async def get_strategy_detail(
    strategy_code: str,
    user_id: str | None = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    sid = await resolver.strategy_code_to_id(db, strategy_code)
    data = await strategy_svc.get_strategy_detail(db, sid, user_id=user_id)
    return success(data, rid)


# ---------------------------------------------------------------- equity curve


@router.get("/{strategy_code}/equity-curve")
async def get_equity_curve(
    strategy_code: str,
    period: str | None = Query(None, pattern=r"^(1m|3m|6m|1y|3y|all)$"),
    start_date: date | None = None,
    end_date: date | None = None,
    include_benchmark: bool = True,
    include_drawdown: bool = True,
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    sid = await resolver.strategy_code_to_id(db, strategy_code)
    data = await strategy_svc.get_equity_curve(
        db,
        strategy_id=sid,
        strategy_code=strategy_code,
        period=period,
        start_date=start_date,
        end_date=end_date,
        include_benchmark=include_benchmark,
        include_drawdown=include_drawdown,
    )
    return success(data, rid)


# ---------------------------------------------------------------- monthly returns


@router.get("/{strategy_code}/monthly-returns")
async def get_monthly_returns(
    strategy_code: str,
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    sid = await resolver.strategy_code_to_id(db, strategy_code)
    data = await strategy_svc.get_monthly_returns(
        db,
        strategy_id=sid,
        strategy_code=strategy_code,
    )
    return success(data, rid)


# ---------------------------------------------------------------- backtest report


@router.get("/{strategy_code}/backtest-report")
async def get_backtest_report(
    strategy_code: str,
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    sid = await resolver.strategy_code_to_id(db, strategy_code)
    data = await strategy_svc.get_backtest_report(
        db,
        strategy_id=sid,
        strategy_code=strategy_code,
    )
    return success(data, rid)


# ---------------------------------------------------------------- trades


@router.get("/{strategy_code}/trades")
async def list_trades(
    strategy_code: str,
    start_date: date | None = None,
    end_date: date | None = None,
    action: str | None = Query(None, pattern=r"^(all|buy|sell)$"),
    result: str | None = Query(None, pattern=r"^(all|win|loss)$"),
    page: PageParams = Depends(page_dep),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    sid = await resolver.strategy_code_to_id(db, strategy_code)
    items, total = await strategy_svc.list_trades(
        db,
        strategy_id=sid,
        strategy_code=strategy_code,
        start_date=start_date,
        end_date=end_date,
        action=action,  # type: ignore[arg-type]
        result=result,  # type: ignore[arg-type]
        page=page,
    )
    return success(
        {"list": items, "pagination": make_pagination(page, total)},
        rid,
    )


# ---------------------------------------------------------------- signals of strategy


@router.get("/{strategy_code}/signals")
async def list_signals_of_strategy(
    strategy_code: str,
    type: str | None = Query(None, pattern=r"^(entry|exit|adjust|alert|all)$"),
    action: str | None = Query(None, pattern=r"^(buy|sell|hold|close|all)$"),
    status: str | None = Query(None, pattern=r"^(active|expired|cancelled|all)$"),
    page: PageParams = Depends(page_dep),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    sid = await resolver.strategy_code_to_id(db, strategy_code)
    items, total = await strategy_svc.list_signals_of_strategy(
        db,
        strategy_id=sid,
        type_=type,
        action=action,
        status=status,
        page=page,
    )
    return success(
        {"list": items, "pagination": make_pagination(page, total)},
        rid,
    )


# ---------------------------------------------------------------- update strategy


class UpdateStrategyRequest(BaseModel):
    """可部分更新的策略字段。仅传入的字段会被更新，未传入的保持不变。"""

    name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = None
    # `detail_html` carries the user-supplied rich content rendered in
    # `frontend/src/pages/StrategyDetail.tsx`. Hard-capped at 50,000 chars
    # to match the Postgres CHECK constraint in
    # `migrations/024_*.sql` and the frontend zod schema in
    # `frontend/src/pages/StrategyEdit.tsx`. Bleach normalization in
    # `services/sanitize.py` runs at the service layer; Pydantic only
    # enforces the length ceiling here.
    detail_html: str | None = Field(None, max_length=50_000)
    category_id: str | None = None
    asset_class: str | None = None
    market: str | None = None
    risk_level: str | None = None
    run_status: str | None = None
    subscription_monthly: float | None = Field(None, ge=0)
    subscription_yearly: float | None = Field(None, ge=0)
    backtest_start: date | None = None
    backtest_end: date | None = None


@router.put("/{strategy_code}")
async def update_strategy(
    strategy_code: str,
    body: UpdateStrategyRequest,
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    sid = await resolver.strategy_code_to_id(db, strategy_code)
    fields: dict[str, Any] = body.model_dump(exclude_none=True)
    data = await strategy_svc.update_strategy(db, strategy_id=sid, user_id=user_id, **fields)
    return success(data, rid)
