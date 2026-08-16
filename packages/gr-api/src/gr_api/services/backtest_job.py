"""Backtest job read + execution service.

Persisted backtest job lifecycle metadata is business/task-orchestration data,
so all reads, the cancel transition, and execution requests come from
PostgreSQL. ClickHouse and DuckDB are intentionally not involved here.

The execution helpers (`create_*_job`, `run_job_synchronously`) write a
queued ``backtest_jobs`` row, return a fresh ``ref_id``, and (on demand)
invoke a ``BacktestJobOp`` inside ``BacktestJobRunner.run_once()``. P0
executes jobs in-process via ``asyncio.to_thread``; a real worker pool
replaces this without changing the public surface.

All read and cancel paths are owner-scoped: callers must pass the
authenticated ``user_id`` (string UUID). When a caller without a user
context (e.g. the in-process runner) needs to read a job, it must
pass the ``_SYSTEM_USER_ID`` sentinel to bypass the filter.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from gr_api.errors import Conflict, NotFound
from gr_api.jobs.ops import get_op_for_job_type
from gr_api.jobs.persistence import PgBacktestJobStore
from gr_api.jobs.runner import BacktestJobRunner


if TYPE_CHECKING:
    from fastapi import Request
    from gr_api.pagination import PageParams
    from gr_api.schemas.backtest import (
        BacktestRunRequest,
        SweepRunRequest,
        WalkForwardRunRequest,
    )
    from gr_api.services.job_listener import BacktestJobListener
    from psycopg import AsyncConnection


logger = logging.getLogger(__name__)


_STORE = PgBacktestJobStore()

# Sentinel for "no owner scoping" — used by the in-process runner and
# idempotency lookup that legitimately needs to read any user's job.
# Mirrors ``_SYSTEM_USER`` in the persistence layer.
_SYSTEM_USER_ID = "*"


_CANCELLABLE_STATUSES = frozenset({"queued", "running"})

# Round #1063 — pg_notify cross-process push. The FastAPI ``lifespan``
# in ``apps/web/main.py`` instantiates a single ``BacktestJobListener``
# per process and assigns it here. The SSE generator below uses it
# to wake up within ~10ms of a worker-side row UPDATE instead of
# waiting up to ``_POLL_INTERVAL_S`` (1s) for the next poll tick.
# The 1s poll remains as a safety net via the ``wait_for`` timeout.
# ``None`` in tests (no lifespan) — the generator falls back to
# pure polling, identical to pre-#1063 behaviour.
_LISTENER: BacktestJobListener | None = None


async def list_jobs(
    db: AsyncConnection,
    *,
    job_type: str | None,
    status: str | None,
    page: PageParams,
    user_id: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """List persisted backtest jobs with optional filters.

    When ``user_id`` is provided, only jobs owned by that user are
    returned. When omitted (``None``), the store applies no owner
    filter — only the in-process runner should use this mode.
    """
    rows, total = await _STORE.list_jobs(
        job_type=job_type,
        status=status,
        user_id=user_id if user_id is not None else _SYSTEM_USER_ID,
        limit=page.limit,
        offset=page.offset,
        conn=db,
    )
    return [_job_summary(row) for row in rows], total


async def get_job(
    db: AsyncConnection,
    job_id: str,
    *,
    user_id: str,
) -> dict[str, Any]:
    """Return one persisted backtest job detail.

    Cross-user lookups raise ``NotFound`` to avoid leaking the
    existence of a job the caller does not own.
    """
    row = await _STORE.get_job(job_id, user_id=user_id, conn=db)
    if row is None:
        raise NotFound(f"backtest job not found: {job_id}")
    return _job_detail(row)


async def cancel_job(db: AsyncConnection, job_id: str, *, user_id: str) -> dict[str, Any]:
    """Cancel a job that is still queued or running.

    Raises ``NotFound`` when the job is missing **or** the caller is not
    the owner, and ``Conflict`` when the current status is not
    cancellable (already completed, failed, or cancelled).

    P3 Worker Pool round: cancel transport is now DB-driven. The
    runner's per-trial ``_is_cancelled`` probe reads
    ``backtest_jobs.status`` directly, so any process — the in-process
    API fallback or a Celery worker — observes the cancel on the next
    trial / window boundary (typically ≤1s). The legacy in-process
    event helper was removed; the in-memory active registry is gone.
    """
    existing = await _STORE.get_job(job_id, user_id=user_id, conn=db)
    if existing is None:
        raise NotFound(f"backtest job not found: {job_id}")
    if existing["status"] not in _CANCELLABLE_STATUSES:
        raise Conflict(
            f"backtest job {job_id} cannot be cancelled in status {existing['status']!r}"
        )
    updated = await _STORE.mark_cancelled(job_id, user_id=user_id, conn=db)
    if not updated:
        # Concurrent cancel/deleted the row between our check and update.
        raise NotFound(f"backtest job not found after cancel: {job_id}")

    refreshed = await _STORE.get_job(job_id, user_id=_SYSTEM_USER_ID, conn=db)
    # ``refreshed`` should be non-None because we just updated an existing row,
    # but guard defensively to avoid an AttributeError on a dropped row.
    if refreshed is None:
        raise NotFound(f"backtest job not found after cancel: {job_id}")
    return _job_detail(refreshed)


# ---------------------------------------------------------------- execution


def _request_payload(body: Any) -> dict[str, Any]:
    """Materialize a Pydantic model as a JSON-safe ``request_json`` dict.

    Pydantic v2 ``BaseModel`` exposes ``model_dump(mode="json")`` which
    recursively converts ``Decimal``/``datetime`` to JSON-safe scalars.
    """
    if hasattr(body, "model_dump"):
        return body.model_dump(mode="json")
    if isinstance(body, dict):
        return dict(body)
    raise TypeError(f"unsupported request body type: {type(body).__name__}")


# Server-stamped keys that must not contribute to the body fingerprint.
# ``_idempotency_key`` is appended *after* the canonical form is built, and
# ``_user_id`` is the legacy JSONB owner key (now stored as a column).
_STRIPPED_KEYS = frozenset({"_idempotency_key", "_user_id"})


def _body_fingerprint(body: Any) -> str:
    """Return the sha256-hex digest of the canonical request body.

    Canonical form = ``body.model_dump(mode="json")`` (same as
    ``_request_payload``), then drop any server-stamped keys
    (``_idempotency_key``, legacy ``_user_id``), then ``json.dumps`` with
    sorted keys + compact separators so re-dumps of the same logical
    payload always hash to the same digest. The two helpers therefore
    agree on what the store stores, and what the idempotency lookup
    compares against.
    """
    payload = _request_payload(body)
    for key in _STRIPPED_KEYS:
        payload.pop(key, None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _create_job(
    db: AsyncConnection,
    *,
    job_type: str,
    body: Any,
    user_id: str | None,
    explicit_ref_id: str | None = None,
    idempotency_key: str | None = None,
    max_attempts: int = 1,
    retry_base_seconds: float | None = None,
    retry_cap_seconds: float | None = None,
    retry_jitter_pct: float | None = None,
) -> tuple[str, str]:
    """Create a queued job row and return ``(job_id, ref_id)``.

    The owner is stored in the row's ``user_id`` column; the JSONB
    ``_user_id`` legacy key is no longer written. The sha256-hex of the
    canonical body is stored in ``request_hash`` so future POSTs with the
    same ``Idempotency-Key`` can be checked for body equality.
    """
    ref_id = explicit_ref_id or uuid4().hex
    payload = _request_payload(body)
    if idempotency_key is not None:
        payload["_idempotency_key"] = idempotency_key
    request_hash = _body_fingerprint(body)
    job_id = await _STORE.create_job(
        job_type=job_type,
        ref_id=ref_id,
        request_json=payload,
        request_hash=request_hash,
        max_attempts=max(1, int(max_attempts)),
        user_id=user_id,
        retry_base_seconds=retry_base_seconds,
        retry_cap_seconds=retry_cap_seconds,
        retry_jitter_pct=retry_jitter_pct,
        conn=db,
    )
    return job_id, ref_id


async def _resolve_idempotent(
    db: AsyncConnection,
    *,
    user_id: str | None,
    idempotency_key: str | None,
    body: Any,
) -> tuple[str, str] | None:
    """Look up an existing job by ``_idempotency_key``; return its pair or ``None``.

    When an existing row is found, the canonical body fingerprint is
    compared to the row's stored ``request_hash``. A mismatch raises
    ``Conflict`` (HTTP 409 via the global exception handler). A
    ``request_hash`` of ``None`` (legacy row created before migration
    023) is treated as a permissive match to avoid breaking in-flight
    idempotency keys at the cutover boundary.
    """
    if not idempotency_key:
        return None
    existing = await _STORE.get_by_idempotency_key(
        key=idempotency_key,
        user_id=user_id,
        conn=db,
    )
    if existing is None:
        return None
    stored_hash = existing.get("request_hash")
    if stored_hash is not None and stored_hash != "":
        incoming_hash = _body_fingerprint(body)
        if stored_hash != incoming_hash:
            raise Conflict(
                f"idempotency key {idempotency_key!r} was previously used "
                f"with a different request body"
            )
    return existing["job_id"], existing["ref_id"]


async def create_backtest_job(
    db: AsyncConnection,
    body: BacktestRunRequest,
    *,
    user_id: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[str, str]:
    """Create a queued ``backtest`` job and return ``(job_id, run_id)``."""
    if (
        hit := await _resolve_idempotent(
            db, user_id=user_id, idempotency_key=idempotency_key, body=body
        )
    ) is not None:
        return hit
    return await _create_job(
        db,
        job_type="backtest",
        body=body,
        user_id=user_id,
        idempotency_key=idempotency_key,
        max_attempts=body.max_attempts,
        retry_base_seconds=body.retry_base_seconds,
        retry_cap_seconds=body.retry_cap_seconds,
        retry_jitter_pct=body.retry_jitter_pct,
    )


async def create_sweep_job(
    db: AsyncConnection,
    body: SweepRunRequest,
    *,
    user_id: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[str, str]:
    """Create a queued ``sweep`` job and return ``(job_id, sweep_id)``.

    The caller may provide an explicit ``sweep_id`` on the request; if so it
    is used as the ``ref_id`` so the persisted sweep parent row matches.
    """
    if (
        hit := await _resolve_idempotent(
            db, user_id=user_id, idempotency_key=idempotency_key, body=body
        )
    ) is not None:
        return hit
    explicit = getattr(body, "sweep_id", None)
    return await _create_job(
        db,
        job_type="sweep",
        body=body,
        user_id=user_id,
        explicit_ref_id=explicit,
        idempotency_key=idempotency_key,
        max_attempts=body.max_attempts,
        retry_base_seconds=body.retry_base_seconds,
        retry_cap_seconds=body.retry_cap_seconds,
        retry_jitter_pct=body.retry_jitter_pct,
    )


async def create_walk_forward_job(
    db: AsyncConnection,
    body: WalkForwardRunRequest,
    *,
    user_id: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[str, str]:
    """Create a queued ``walk_forward`` job and return ``(job_id, walk_forward_id)``.

    Honors an explicit ``walk_forward_id`` on the request when supplied.
    """
    if (
        hit := await _resolve_idempotent(
            db, user_id=user_id, idempotency_key=idempotency_key, body=body
        )
    ) is not None:
        return hit
    explicit = getattr(body, "walk_forward_id", None)
    return await _create_job(
        db,
        job_type="walk_forward",
        body=body,
        user_id=user_id,
        explicit_ref_id=explicit,
        idempotency_key=idempotency_key,
        max_attempts=body.max_attempts,
        retry_base_seconds=body.retry_base_seconds,
        retry_cap_seconds=body.retry_cap_seconds,
        retry_jitter_pct=body.retry_jitter_pct,
    )


async def run_job_synchronously(job_id: str) -> dict[str, Any]:
    """Execute one queued job to completion via ``BacktestJobRunner``.

    Looks up the job to determine its ``job_type``, instantiates the
    matching ``BacktestJobOp``, then runs ``runner.run_once()`` in a
    worker thread (via ``asyncio.to_thread``) to avoid blocking the event
    loop. Returns the lifecycle result as a plain dict.

    Errors raised by the op are captured by the runner and recorded on
    the job row; this function itself does not re-raise them.

    The runner operates without a user context, so it bypasses the
    owner-scope filter by passing the system sentinel. A libpq DSN
    is threaded into the runner so its per-trial cancel probe can
    observe DB-side ``status='cancelled'`` writes from any process.
    """
    from gr_data.config.settings import make_pg_dsn, settings

    row = await _STORE.get_job(job_id, user_id=_SYSTEM_USER_ID)
    if row is None:
        raise NotFound(f"backtest job not found: {job_id}")
    op = get_op_for_job_type(row["job_type"])
    runner = BacktestJobRunner(
        _STORE,
        op,
        job_type=row["job_type"],
        sleep_seconds=0,
        db_conninfo=make_pg_dsn(settings.postgres),
    )
    result = await asyncio.to_thread(_run_once_sync, runner)
    return result.to_dict()


def _run_once_sync(runner: BacktestJobRunner) -> Any:
    """Run ``runner.run_once()`` in a thread to keep the event loop responsive."""
    return asyncio.run(runner.run_once())


# ---------------------------------------------------------------- helpers


def _job_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": row["job_id"],
        "job_type": row["job_type"],
        "ref_id": row["ref_id"],
        "status": row["status"],
        "progress": row["progress"],
        "error_message": row["error_message"],
        "created_at": _dt(row["created_at"]),
        "started_at": _dt_nullable(row["started_at"]),
        "completed_at": _dt_nullable(row["completed_at"]),
        "updated_at": _dt(row["updated_at"]),
    }


def _job_detail(row: dict[str, Any]) -> dict[str, Any]:
    data = _job_summary(row)
    data["request_json"] = _json_value(row["request_json"], {})
    return data


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _dt(value: datetime | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _dt_nullable(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    return _dt(value)


# ---------------------------------------------------------------- SSE


# Polling cadence + heartbeat + SSE frame encoding are now centralised
# in ``gr_api.services.sse`` (Round #1061). The aliases below
# keep the rest of this module's internals readable and the existing
# test fixtures' monkeypatch sites (e.g. ``_POLL_INTERVAL_S = 0.05``)
# working — the constants are imported, not redefined.
from gr_api.services.sse import (  # noqa: E402  (import after constants)
    HEARTBEAT_INTERVAL_S as _HEARTBEAT_INTERVAL_S,
    POLL_INTERVAL_S as _POLL_INTERVAL_S,
    SSE_HEARTBEAT as _SSE_HEARTBEAT,
    TERMINAL_STATUSES as _TERMINAL_STATUSES,
    sse_frame as _sse_frame,
)


async def stream_job_events(
    *,
    job_id: str,
    user_id: str,
    request: Request,
    last_event_id: str | None = None,
) -> AsyncIterator[bytes]:
    """Yield SSE-encoded bytes for one job's lifecycle.

    Event sequence on a healthy stream::

        event: snapshot
        id: <updated_at>
        data: <BacktestJobDetail>
        ...
        event: update
        id: <updated_at>
        data: <BacktestJobDetail>
        ...
        event: done
        id: <updated_at>
        data: <BacktestJobDetail>

    Every data-bearing frame carries an SSE ``id:`` field set to the
    row's ``updated_at`` ISO string. A reconnecting client sends the
    last id it received as the ``Last-Event-ID`` request header; the
    router forwards it as ``last_event_id`` here. We do NOT replay
    events from a log (Round #1058 trade-off: the polling loop re-emits
    the current snapshot on reconnect, so at most one in-flight update
    is lost — same as the previous 5 s polling cadence). The header is
    plumbed end-to-end so a future event-log feature is a drop-in
    addition.

    Heartbeats (``:keepalive``) fire every ``_HEARTBEAT_INTERVAL_S``
    if no other event was sent. The generator returns early when:

    * the request client disconnects (``request.is_disconnected()``);
    * the job reaches a terminal status (``done`` then close);
    * a mid-stream DB read raises (``event: error`` then close);
    * the row is deleted mid-stream (treated as ``cancelled``).

    Cross-user or missing rows raise ``NotFound`` from the initial
    read; FastAPI's global handler turns it into HTTP 404 — we never
    open the stream in that case.
    """
    # 1) Initial snapshot + owner-scope check.
    first_row = await _STORE.get_job(job_id, user_id=user_id)
    if first_row is None:
        raise NotFound(f"backtest job not found: {job_id}")

    last_payload = _job_detail(first_row)
    snapshot_id = str(last_payload["updated_at"])
    yield _sse_frame("snapshot", last_payload, event_id=snapshot_id)

    if first_row["status"] in _TERMINAL_STATUSES:
        # Job already finished before the page connected. Skip the
        # poll loop entirely — client gets final state in frame 1+2.
        yield _sse_frame("done", last_payload, event_id=snapshot_id)
        return

    last_etag = (
        last_payload["status"],
        last_payload["progress"],
        last_payload["updated_at"],
    )
    loop = asyncio.get_running_loop()
    next_heartbeat = loop.time() + _HEARTBEAT_INTERVAL_S

    # Round #1063 — subscribe to the listener (if any) so a worker-
    # side ``pg_notify`` wakes the poll loop within ~10ms. The
    # ``wait_for`` timeout below is the polling safety net.
    listener = _LISTENER
    ev = listener.subscribe(job_id) if listener is not None else None
    try:
        # 2) Poll loop.
        while True:
            if ev is not None:
                try:
                    await asyncio.wait_for(ev.wait(), timeout=_POLL_INTERVAL_S)
                    ev.clear()
                except asyncio.TimeoutError:
                    pass
                    # silent-fail-ok: 超时后退回轮询数据库是既定设计
                    # （见 Round #1058），这里吞掉异常是有意的。
            else:
                try:
                    await asyncio.sleep(_POLL_INTERVAL_S)
                except asyncio.CancelledError:
                    return

            if await request.is_disconnected():
                return

            # Heartbeat if we have not sent anything in a while.
            now = loop.time()
            if now >= next_heartbeat:
                yield _SSE_HEARTBEAT
                next_heartbeat = now + _HEARTBEAT_INTERVAL_S

            try:
                row = await _STORE.get_job(job_id, user_id=user_id)
            except Exception:  # noqa: BLE001
                logger.exception("SSE poll failed for job %s", job_id)
                yield _sse_frame("error", {"detail": "internal read error"})
                return

            if row is None:
                # Row deleted mid-stream — treat as cancelled.
                yield _sse_frame(
                    "done",
                    {"job_id": job_id, "status": "cancelled"},
                    event_id=snapshot_id,
                )
                return

            payload = _job_detail(row)
            etag = (payload["status"], payload["progress"], payload["updated_at"])
            if etag != last_etag:
                frame_id = str(payload["updated_at"])
                yield _sse_frame("update", payload, event_id=frame_id)
                last_etag = etag
                last_payload = payload
                snapshot_id = frame_id
                # A real change counts as activity — reset heartbeat clock.
                next_heartbeat = loop.time() + _HEARTBEAT_INTERVAL_S

            if row["status"] in _TERMINAL_STATUSES:
                yield _sse_frame("done", payload, event_id=snapshot_id)
                return
    finally:
        if listener is not None:
            listener.unsubscribe(job_id)
