"""Walk-forward study read endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse

from getrich.apps.web.deps import get_db, page_dep, request_id, require_user
from getrich.apps.web.pagination import make_pagination
from getrich.apps.web.response import success
from getrich.apps.web.services import backtest_walk_forward as walk_forward_svc


if TYPE_CHECKING:
    from psycopg import AsyncConnection

    from getrich.apps.web.pagination import PageParams


router = APIRouter(prefix="/backtest-walk-forwards", tags=["backtest"])


@router.get("")
async def list_walk_forwards(
    status: str | None = Query(None, pattern=r"^(running|completed|failed)$"),
    page: PageParams = Depends(page_dep),
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    items, total = await walk_forward_svc.list_walk_forwards(
        db,
        status=status,
        page=page,
        user_id=user_id,
    )
    return success({"list": items, "pagination": make_pagination(page, total)}, rid)


@router.get("/{walk_forward_id}")
async def get_walk_forward(
    walk_forward_id: str,
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    data = await walk_forward_svc.get_walk_forward(db, walk_forward_id, user_id=user_id)
    return success(data, rid)


@router.get("/{walk_forward_id}/events")
async def stream_walk_forward_events(
    walk_forward_id: str,
    request: Request,
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    """Stream lifecycle events for one walk-forward study (SSE).

    Companion to :func:`backtest_jobs.stream_job_events` but keyed on
    the *walk-forward* row instead of the parent job. The result
    page can open the stream as soon as the page has a
    ``walk_forward_id``; it does not need to wait for the runner
    to claim the parent job. The payload is the
    :func:`get_walk_forward` detail with the parent job's live
    ``progress`` / ``job_status`` merged in.

    Owner-scope is enforced server-side. The pre-flight
    :func:`walk_forward_svc.get_walk_forward` runs in the route
    handler so a cross-user / missing-study lookup returns 404
    cleanly (the ``StreamingResponse`` has not yet flushed its
    200 + headers). See
    :func:`backtest_walk_forward.stream_walk_forward_events` for
    the full generator contract.
    """
    # Pre-flight owner-scope check — must run before the
    # StreamingResponse starts so the global exception handler can
    # convert NotFound to a clean 404 JSON response.
    await walk_forward_svc.get_walk_forward(db, walk_forward_id, user_id=user_id)
    return StreamingResponse(
        walk_forward_svc.stream_walk_forward_events(
            walk_forward_id=walk_forward_id,
            user_id=user_id,
            request=request,
            last_event_id=last_event_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # disable nginx buffering
            "Connection": "keep-alive",
        },
    )


@router.get("/{walk_forward_id}/windows")
async def list_windows(
    walk_forward_id: str,
    status: str | None = Query(None, pattern=r"^(completed|failed)$"),
    page: PageParams = Depends(page_dep),
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    items, total = await walk_forward_svc.list_windows(
        db,
        walk_forward_id,
        status=status,
        page=page,
        user_id=user_id,
    )
    return success({"list": items, "pagination": make_pagination(page, total)}, rid)


@router.get("/{walk_forward_id}/oos-equity-curve")
async def get_oos_equity_curve(
    walk_forward_id: str,
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    points = await walk_forward_svc.get_oos_equity_curve(
        db,
        walk_forward_id,
        user_id=user_id,
    )
    return success({"points": points, "total_points": len(points)}, rid)
