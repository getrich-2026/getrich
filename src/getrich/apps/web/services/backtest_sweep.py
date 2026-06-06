"""Backtest sweep read service.

Persisted parameter sweep metadata is business/research state, so all reads
come from PostgreSQL. ClickHouse/DuckDB are intentionally not involved here.

All read endpoints are owner-scoped: callers must pass the authenticated
``user_id``. Cross-user access raises ``NotFound`` to avoid leaking
existence of resources the caller does not own.

Sweep ↔ job linkage
-------------------
A sweep result row is only written after the runner completes (and saves
the result back to ``backtest_sweeps``). Between ``POST /v1/backtest-jobs/sweep``
and the runner's first save, the only thing that exists is the
``backtest_jobs`` row whose ``ref_id`` equals the sweep's id. To let the
frontend open ``/backtest-jobs/{job_id}/events`` for live progress *before*
the sweep row is finalised, this service also looks up the related job
via ``ref_id`` and exposes ``job_id`` / ``progress`` / ``job_status``.
These three fields are ``None`` in the brief window between job create
and runner claim (typically <1s).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from fastapi import Request

from getrich.apps.web.errors import NotFound
from getrich.apps.web.services.sse import (
    HEARTBEAT_INTERVAL_S as _HEARTBEAT_INTERVAL_S,
    POLL_INTERVAL_S as _POLL_INTERVAL_S,
    SSE_HEARTBEAT as _SSE_HEARTBEAT,
    TERMINAL_STATUSES as _TERMINAL_STATUSES,
    sse_frame as _sse_frame,
)
from getrich_backtest.job_persistence import PgBacktestJobStore
from getrich_backtest.sweep_persistence import PgSweepResultStore, SweepPersistenceError


if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from psycopg import AsyncConnection

    from getrich.apps.web.pagination import PageParams
    from getrich.apps.web.services.job_listener import BacktestJobListener


_STORE = PgSweepResultStore()
_JOB_STORE = PgBacktestJobStore()

# Round #1063 — pg_notify cross-process push. See
# ``backtest_job._LISTENER`` for the rationale; the sweep and
# walk-forward generators share the same listener instance via the
# FastAPI ``lifespan``. None in tests → pure polling fallback.
_LISTENER: BacktestJobListener | None = None


async def list_sweeps(
    db: AsyncConnection,
    *,
    status: str | None,
    page: PageParams,
    user_id: str,
) -> tuple[list[dict[str, Any]], int]:
    """List persisted parameter sweeps owned by ``user_id`` with optional filters."""
    rows, total = await _STORE.list_sweeps(
        status=status,
        user_id=user_id,
        limit=page.limit,
        offset=page.offset,
        conn=db,
    )
    return [_sweep_summary(row) for row in rows], total


async def get_sweep(
    db: AsyncConnection,
    sweep_id: str,
    *,
    user_id: str,
) -> dict[str, Any]:
    """Return one persisted parameter sweep detail owned by ``user_id``.

    The detail also includes ``job_id`` / ``progress`` / ``job_status``
    sourced from ``backtest_jobs`` via the ``ref_id`` linkage. These
    are ``None`` until the runner claims the job (or if the runner has
    been garbage-collected with no retry).
    """
    row = await _STORE.get_sweep(sweep_id, user_id=user_id, conn=db)
    if row is None:
        raise NotFound(f"backtest sweep not found: {sweep_id}")
    job_row = await _JOB_STORE.get_job_by_ref_id(sweep_id, user_id=user_id, conn=db)
    return _sweep_detail(row, job_row)


async def stream_sweep_events(
    *,
    sweep_id: str,
    user_id: str,
    request: Request,
    last_event_id: str | None = None,  # noqa: ARG001  (plumbed for future event-log)
) -> AsyncIterator[bytes]:
    """Yield SSE-encoded bytes for one sweep's lifecycle.

    The wire format and lifecycle mirror :func:`backtest_job.stream_job_events`
    (``snapshot`` → ``update`` * N → ``done`` + close), with two
    differences worth calling out:

    1. **Payload shape.** The ``data:`` payload is the
       :func:`_sweep_detail` of the sweep row, with the parent
       ``backtest_jobs`` row merged in for live ``progress`` /
       ``job_status``. This matches the ``BacktestSweepDetail`` the
       frontend already caches via ``getBacktestSweep`` — the page
       can ``setQueryData`` the whole row without a bespoke merge
       step (Round #1060's Cancel-button work patched over the
       gap; the dedicated endpoint removes the indirection).

    2. **Terminal detection.** A sweep is considered "done" when
       the *parent job* reaches a terminal status (``completed`` /
       ``failed`` / ``cancelled``), not when the sweep row itself
       flips to ``completed`` / ``failed``. Reason: the runner
       writes the sweep result row *after* it has finished, so
       using the sweep's own status would either race the runner
       (sweep is "running" right up until the moment it's "completed")
       or miss the cancel path entirely (cancelled is not a valid
       sweep status — see ``sweep_persistence.py:23``). Using the
       job's status is robust to both.

    Cross-user or missing sweep rows raise ``NotFound`` from the
    initial read; FastAPI's global handler turns it into HTTP 404
    before the stream opens.
    """
    # 1) Initial snapshot + owner-scope check.
    first_sweep = await _STORE.get_sweep(sweep_id, user_id=user_id)
    if first_sweep is None:
        raise NotFound(f"backtest sweep not found: {sweep_id}")
    first_job = await _JOB_STORE.get_job_by_ref_id(
        sweep_id,
        user_id=user_id,
    )
    last_payload = _sweep_detail(first_sweep, first_job)
    snapshot_id = str(last_payload["updated_at"])
    yield _sse_frame("snapshot", last_payload, event_id=snapshot_id)

    if _is_terminal_payload(last_payload):
        # Sweep is already done before the page connected. Skip the
        # poll loop entirely — client gets final state in frame 1+2.
        yield _sse_frame("done", last_payload, event_id=snapshot_id)
        return

    last_etag = _payload_etag(last_payload)
    loop = asyncio.get_running_loop()
    next_heartbeat = loop.time() + _HEARTBEAT_INTERVAL_S

    # Round #1063 — subscribe to the listener on the parent job_id.
    # The sweep's own status is written post-run, but the parent
    # backtest_jobs row is the lifecycle carrier (progress ticks
    # land here) and is the only thing the worker side NOTIFYs.
    # ``first_job`` is None only in the vanishingly rare window
    # before the API POST inserts the backtest_jobs row — in that
    # case the 1s poll safety net covers the gap.
    listener = _LISTENER
    parent_job_id = first_job["job_id"] if first_job is not None else None
    ev = (
        listener.subscribe(parent_job_id)
        if (listener is not None and parent_job_id is not None)
        else None
    )
    try:
        # 2) Poll loop.
        while True:
            if ev is not None:
                try:
                    await asyncio.wait_for(ev.wait(), timeout=_POLL_INTERVAL_S)
                    ev.clear()
                except asyncio.TimeoutError:
                    pass
                    # silent-fail-ok: timer-based fallthrough to DB poll is the documented design (Round #1058)
            else:
                try:
                    await asyncio.sleep(_POLL_INTERVAL_S)
                except asyncio.CancelledError:
                    return

            if await request.is_disconnected():
                return

            try:
                sweep_row = await _STORE.get_sweep(sweep_id, user_id=user_id)
                job_row = await _JOB_STORE.get_job_by_ref_id(
                    sweep_id,
                    user_id=user_id,
                )
            except Exception:
                # A mid-stream read failure closes the connection with an
                # explicit error frame. The client treats this as a
                # hard-stop and surfaces the error to the user.
                yield _sse_frame(
                    "error",
                    {"detail": "internal read error"},
                )
                return

            if sweep_row is None:
                # Sweep row vanished (e.g. admin cleanup). Treat as
                # cancelled — matches the job-stream contract.
                last_payload = _sweep_detail(
                    {
                        "sweep_id": sweep_id,
                        "status": "cancelled",
                        "updated_at": last_payload["updated_at"],
                        "created_at": last_payload["created_at"],
                        "completed_at": None,
                        "search_type": last_payload["search_type"],
                        "search_spec": last_payload["search_spec"],
                        "select_metric": last_payload["select_metric"],
                        "maximize": last_payload["maximize"],
                        "total_trials": last_payload["total_trials"],
                        "completed_trials": last_payload["completed_trials"],
                        "failed_trials": last_payload["failed_trials"],
                        "best_trial_id": last_payload["best_trial_id"],
                        "best_run_id": last_payload["best_run_id"],
                        "best_metric_value": last_payload["best_metric_value"],
                        "summary_json": last_payload["summary_json"],
                    },
                    job_row,
                )
                yield _sse_frame(
                    "done",
                    last_payload,
                    event_id=str(last_payload["updated_at"]),
                )
                return

            payload = _sweep_detail(sweep_row, job_row)
            etag = _payload_etag(payload)
            now = loop.time()

            if etag == last_etag:
                # Heartbeat to keep idle connections alive across proxies.
                if now >= next_heartbeat:
                    yield _SSE_HEARTBEAT
                    next_heartbeat = now + _HEARTBEAT_INTERVAL_S
                continue

            last_etag = etag
            next_heartbeat = now + _HEARTBEAT_INTERVAL_S
            yield _sse_frame(
                "update",
                payload,
                event_id=str(payload["updated_at"]),
            )

            if _is_terminal_payload(payload):
                yield _sse_frame(
                    "done",
                    payload,
                    event_id=str(payload["updated_at"]),
                )
                return
    finally:
        if listener is not None and parent_job_id is not None:
            listener.unsubscribe(parent_job_id)


async def list_sweep_trials(
    db: AsyncConnection,
    sweep_id: str,
    *,
    status: str | None,
    page: PageParams,
    user_id: str,
) -> tuple[list[dict[str, Any]], int]:
    """List persisted trial rows for one parameter sweep owned by ``user_id``."""
    try:
        rows, total = await _STORE.list_sweep_trials(
            sweep_id,
            status=status,
            user_id=user_id,
            limit=page.limit,
            offset=page.offset,
            conn=db,
        )
    except SweepPersistenceError as exc:
        # Translate persistence-layer "owner miss" into the web-layer
        # 404 surface so callers cannot probe for resource existence
        # by walking the API.
        raise NotFound(f"backtest sweep not found: {sweep_id}") from exc
    return [_trial(row) for row in rows], total


# ---------------------------------------------------------------- helpers


def _sweep_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "sweep_id": row["sweep_id"],
        "search_type": row["search_type"],
        "search_spec": _json_value(row["search_spec"], {}),
        "select_metric": row["select_metric"],
        "maximize": row["maximize"],
        "status": row["status"],
        "total_trials": row["total_trials"],
        "completed_trials": row["completed_trials"],
        "failed_trials": row["failed_trials"],
        "best_trial_id": row["best_trial_id"],
        "best_run_id": row["best_run_id"],
        "best_metric_value": _f_nullable(row["best_metric_value"]),
        "created_at": _dt(row["created_at"]),
        "completed_at": _dt_nullable(row["completed_at"]),
        "updated_at": _dt(row["updated_at"]),
    }


def _sweep_detail(
    row: dict[str, Any],
    job_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = _sweep_summary(row)
    data["summary_json"] = _json_value(row["summary_json"], {})
    # Job linkage — ``job_id`` is the handle the frontend needs to open
    # the existing ``/backtest-jobs/{job_id}/events`` SSE channel. When
    # the runner has not yet claimed the job, ``job_row`` is None and
    # the frontend falls back to the sweep's own (terminal) status.
    if job_row is not None:
        data["job_id"] = job_row.get("job_id")
        data["progress"] = int(job_row.get("progress") or 0)
        data["job_status"] = job_row.get("status")
    else:
        data["job_id"] = None
        data["progress"] = None
        data["job_status"] = None
    return data


def _trial(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "trial_id": row["trial_id"],
        "sweep_id": row["sweep_id"],
        "run_id": row["run_id"],
        "trial_index": row["trial_index"],
        "params": _json_value(row["params"], {}),
        "param_fingerprint": row["param_fingerprint"],
        "status": row["status"],
        "error_message": row["error_message"],
        "select_metric_value": _f_nullable(row["select_metric_value"]),
        "metrics_json": _json_value(row["metrics_json"], {}),
        "created_at": _dt(row["created_at"]),
        "completed_at": _dt_nullable(row["completed_at"]),
        "updated_at": _dt(row["updated_at"]),
    }


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _f(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _f_nullable(value: Any) -> float | None:
    if value is None:
        return None
    return _f(value)


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


def _is_terminal_payload(payload: dict[str, Any]) -> bool:
    """True if the SSE payload reflects a finished sweep.

    We key on the parent job's status (merged into ``payload`` via
    ``_sweep_detail``) so cancellation is correctly surfaced — the
    sweep's own status enum has no ``cancelled`` value, and the
    runner flips the job to ``cancelled`` while leaving the sweep
    row's status as ``running`` (cancelled is a top-level cancellation,
    not a sweep lifecycle outcome).
    """
    job_status = payload.get("job_status")
    if job_status is not None:
        return job_status in _TERMINAL_STATUSES
    # No job linkage: fall back to the sweep's own status. This
    # happens in the brief window after row create + before runner
    # claim (job_row is None), or after GC of the job row.
    sweep_status = payload.get("status")
    return sweep_status in {"completed", "failed"}


def _payload_etag(payload: dict[str, Any]) -> tuple[Any, ...]:
    """Coarse de-dup key for SSE updates.

    Two payloads with the same etag do not need a re-emit. The tuple
    covers the live-status surface that the page renders; rows
    can mutate other fields (e.g. ``summary_json``) without
    triggering an update frame.
    """
    return (
        payload.get("status"),
        payload.get("job_status"),
        payload.get("progress"),
        payload.get("updated_at"),
    )
