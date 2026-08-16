"""Backtest job read + execution + cancel endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from gr_api.deps import get_current_user, get_db, page_dep, request_id, require_user
from gr_api.pagination import make_pagination
from gr_api.response import success
from gr_api.schemas.backtest import (
    BacktestRunRequest,
    SweepRunRequest,
    WalkForwardRunRequest,
)
from gr_api.services import backtest_job as job_svc
from gr_data.config.settings import settings


if TYPE_CHECKING:
    from gr_api.pagination import PageParams
    from psycopg import AsyncConnection


router = APIRouter(prefix="/backtest-jobs", tags=["backtest"])


@router.get("")
async def list_jobs(
    job_type: str | None = Query(None, pattern=r"^(backtest|sweep|walk_forward)$"),
    status: str | None = Query(None, pattern=r"^(queued|running|completed|failed|cancelled)$"),
    page: PageParams = Depends(page_dep),
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    items, total = await job_svc.list_jobs(
        db,
        job_type=job_type,
        status=status,
        page=page,
        user_id=user_id,
    )
    return success({"list": items, "pagination": make_pagination(page, total)}, rid)


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    data = await job_svc.get_job(db, job_id, user_id=user_id)
    return success(data, rid)


@router.get("/{job_id}/events")
async def stream_job_events(
    job_id: str,
    request: Request,
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    """Stream lifecycle events for one backtest job (Server-Sent Events).

    Replaces the previous 5 s polling on the detail page with a 1 s
    push. The owner-scope pre-flight runs in the route handler so a
    cross-user lookup returns 404 cleanly (the StreamingResponse has
    not yet flushed its 200 + headers). The generator itself emits
    the snapshot, then ``update`` frames whenever
    ``(status, progress, updated_at)`` changes, and a final ``done``
    frame on terminal status. ``:keepalive`` comment frames fire
    every 15 s on idle connections to keep reverse proxies from
    idling out the stream.

    The optional ``Last-Event-ID`` request header is the SSE
    reconnect token. The frontend SSE client sends the last
    ``id:`` field it received so the server can pick up where the
    client left off. Today we do not replay events from a log (the
    poll loop re-emits the current snapshot, so at most one
    in-flight update is lost — same as 5 s polling). The header is
    plumbed end-to-end so a future event-log feature is drop-in.
    """
    # Pre-flight owner-scope check (raises NotFound on cross-user /
    # missing row) — must run before the StreamingResponse starts so
    # the global exception handler can convert to a clean 404 JSON
    # response.
    await job_svc.get_job(db, job_id, user_id=user_id)
    return StreamingResponse(
        job_svc.stream_job_events(
            job_id=job_id,
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


@router.post("/{job_id}/cancel", status_code=200)
async def cancel_job(
    job_id: str,
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    data = await job_svc.cancel_job(db, job_id, user_id=user_id)
    return success(data, rid)


# ---------------------------------------------------------------- execution


def _enqueue(background: BackgroundTasks, job_id: str, *, task_name: str) -> None:
    """Dispatch a newly created job to inproc BackgroundTasks or Celery.

    The transport is selected at call time via
    :attr:`Settings.worker.backend`:

    * ``inproc`` (default, dev / CI): add the existing
      ``run_job_synchronously`` coroutine to FastAPI's
      ``BackgroundTasks``. The API process runs the job itself.
    * ``celery`` (production): push the task to Redis via
      ``app.send_task(task_name, args=[job_id])``. A separate worker
      process picks it up. The task name is passed explicitly per
      endpoint (backtest.run_job / sweep.run_job /
      walk_forward.run_job) so a rename here ripples through the
      three POST handlers in this module.

    Both paths execute the same underlying
    :class:`BacktestJobRunner.run_once` — only the transport differs.
    Concurrency-safety is provided by
    :meth:`PgBacktestJobStore.claim_next_queued` with
    ``FOR UPDATE SKIP LOCKED`` — if both paths race for the same
    job, only one wins; the loser gets ``claimed=False`` and exits
    cleanly.
    """
    if settings.worker.backend == "celery":
        from gr_api.worker.celery_app import app

        app.send_task(task_name, args=[job_id])
        return
    background.add_task(job_svc.run_job_synchronously, job_id)


@router.post("/backtest", status_code=202)
async def run_backtest(
    body: BacktestRunRequest,
    background: BackgroundTasks,
    user_id: str | None = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    rid: str = Depends(request_id),
):
    job_id, ref_id = await job_svc.create_backtest_job(
        db,
        body,
        user_id=user_id,
        idempotency_key=idempotency_key,
    )
    _enqueue(background, job_id, task_name="backtest.run_job")
    return success({"job_id": job_id, "ref_id": ref_id, "status": "queued"}, rid)


@router.post("/sweep", status_code=202)
async def run_sweep(
    body: SweepRunRequest,
    background: BackgroundTasks,
    user_id: str | None = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    rid: str = Depends(request_id),
):
    job_id, ref_id = await job_svc.create_sweep_job(
        db,
        body,
        user_id=user_id,
        idempotency_key=idempotency_key,
    )
    _enqueue(background, job_id, task_name="sweep.run_job")
    return success({"job_id": job_id, "ref_id": ref_id, "status": "queued"}, rid)


@router.post("/walk-forward", status_code=202)
async def run_walk_forward(
    body: WalkForwardRunRequest,
    background: BackgroundTasks,
    user_id: str | None = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    rid: str = Depends(request_id),
):
    job_id, ref_id = await job_svc.create_walk_forward_job(
        db,
        body,
        user_id=user_id,
        idempotency_key=idempotency_key,
    )
    _enqueue(background, job_id, task_name="walk_forward.run_job")
    return success({"job_id": job_id, "ref_id": ref_id, "status": "queued"}, rid)
