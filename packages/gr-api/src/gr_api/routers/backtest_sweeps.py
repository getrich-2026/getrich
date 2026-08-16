"""Backtest sweep read endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from gr_api.deps import get_db, page_dep, request_id, require_user
from gr_api.pagination import make_pagination
from gr_api.response import success
from gr_api.services import backtest_sweep as sweep_svc


if TYPE_CHECKING:
    from gr_api.pagination import PageParams
    from psycopg import AsyncConnection


router = APIRouter(prefix="/backtest-sweeps", tags=["backtest"])


@router.get("")
async def list_sweeps(
    status: str | None = Query(None, pattern=r"^(running|completed|failed)$"),
    page: PageParams = Depends(page_dep),
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    items, total = await sweep_svc.list_sweeps(
        db,
        status=status,
        page=page,
        user_id=user_id,
    )
    return success({"list": items, "pagination": make_pagination(page, total)}, rid)


@router.get("/{sweep_id}")
async def get_sweep(
    sweep_id: str,
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    data = await sweep_svc.get_sweep(db, sweep_id, user_id=user_id)
    return success(data, rid)


@router.get("/{sweep_id}/events")
async def stream_sweep_events(
    sweep_id: str,
    request: Request,
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    """Stream lifecycle events for one parameter sweep (Server-Sent Events).

    Companion to :func:`backtest_jobs.stream_job_events` but keyed on
    the *sweep* row instead of the parent job. Lets the result page
    open the stream as soon as it has a ``sweep_id`` — no need to
    wait for the runner to claim the job and surface a ``job_id``
    (which can be ``None`` in the brief window between job create
    and runner claim). The payload is the :func:`get_sweep` detail
    with the parent job's live ``progress`` / ``job_status`` merged
    in, so the page can ``setQueryData`` the whole row in one shot.

    Owner-scope is enforced server-side. The pre-flight
    :func:`sweep_svc.get_sweep` runs in the route handler so a
    cross-user / missing-sweep lookup returns 404 cleanly (the
    ``StreamingResponse`` has not yet flushed its 200 + headers).
    See :func:`backtest_sweep.stream_sweep_events` for the full
    generator contract.
    """
    # Pre-flight owner-scope check — must run before the
    # StreamingResponse starts so the global exception handler can
    # convert NotFound to a clean 404 JSON response.
    await sweep_svc.get_sweep(db, sweep_id, user_id=user_id)
    return StreamingResponse(
        sweep_svc.stream_sweep_events(
            sweep_id=sweep_id,
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


@router.get("/{sweep_id}/trials")
async def list_sweep_trials(
    sweep_id: str,
    status: str | None = Query(None, pattern=r"^(completed|failed)$"),
    page: PageParams = Depends(page_dep),
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    items, total = await sweep_svc.list_sweep_trials(
        db,
        sweep_id,
        status=status,
        page=page,
        user_id=user_id,
    )
    return success({"list": items, "pagination": make_pagination(page, total)}, rid)
