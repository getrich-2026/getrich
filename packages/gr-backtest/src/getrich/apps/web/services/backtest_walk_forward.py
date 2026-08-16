"""Walk-forward study read service.

The persisted walk-forward history is business/research metadata, so all reads
come from PostgreSQL. ClickHouse/DuckDB are intentionally not involved here.

All read endpoints are owner-scoped: callers must pass the authenticated
``user_id``. Cross-user access raises ``NotFound`` to avoid leaking
existence of resources the caller does not own.

Walk-forward ↔ job linkage
--------------------------
Mirrors the sweep service: ``backtest_walk_forwards`` is only written
after the runner completes. To support live progress on the result
page, ``get_walk_forward`` looks up the related ``backtest_jobs`` row
via the ``ref_id`` linkage and exposes ``job_id`` / ``progress`` /
``job_status``. The frontend opens
``/backtest-jobs/{job_id}/events`` for the 1Hz push.
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
from getrich_backtest.walk_forward_persistence import PgWalkForwardResultStore


if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from psycopg import AsyncConnection

    from getrich.apps.web.pagination import PageParams
    from getrich.apps.web.services.job_listener import BacktestJobListener


_JOB_STORE = PgBacktestJobStore()
_WF_STORE = PgWalkForwardResultStore()

# Round #1063 — pg_notify cross-process push. See
# ``backtest_job._LISTENER`` for the rationale; the sweep and
# walk-forward generators share the same listener instance via the
# FastAPI ``lifespan``. None in tests → pure polling fallback.
_LISTENER: BacktestJobListener | None = None


async def _assert_walk_forward_owner(
    db: AsyncConnection,
    walk_forward_id: str,
    user_id: str,
) -> None:
    """Raise ``NotFound`` if the study is missing or not owned by ``user_id``."""
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT user_id FROM backtest.backtest_walk_forwards "
            "WHERE walk_forward_id = %(walk_forward_id)s",
            {"walk_forward_id": walk_forward_id},
        )
        row = await cur.fetchone()
    if row is None or row["user_id"] != user_id:
        raise NotFound(f"walk-forward not found: {walk_forward_id}")


async def list_walk_forwards(
    db: AsyncConnection,
    *,
    status: str | None,
    page: PageParams,
    user_id: str,
) -> tuple[list[dict[str, Any]], int]:
    """List persisted walk-forward studies owned by ``user_id`` with optional filters."""
    conds: list[str] = ["user_id = %(user_id)s"]
    params: dict[str, object] = {
        "user_id": user_id,
        "limit": page.limit,
        "offset": page.offset,
    }

    if status:
        conds.append("status = %(status)s")
        params["status"] = status

    where_sql = " AND ".join(conds)
    sql = f"""
        SELECT
            walk_forward_id,
            user_id,
            search_type,
            search_spec,
            select_metric,
            maximize,
            refit,
            status,
            total_windows,
            completed_windows,
            failed_windows,
            mean_validation_metric,
            created_at,
            completed_at,
            updated_at,
            COUNT(*) OVER() AS _total
        FROM backtest.backtest_walk_forwards
        WHERE {where_sql}
        ORDER BY created_at DESC, walk_forward_id DESC
        LIMIT %(limit)s OFFSET %(offset)s
    """

    async with db.cursor() as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()

    total = int(rows[0]["_total"]) if rows else 0
    return [_walk_forward_summary(row) for row in rows], total


async def get_walk_forward(
    db: AsyncConnection,
    walk_forward_id: str,
    *,
    user_id: str,
) -> dict[str, Any]:
    """Return one persisted walk-forward study detail owned by ``user_id``.

    The detail also includes ``job_id`` / ``progress`` / ``job_status``
    sourced from ``backtest_jobs`` via the ``ref_id`` linkage. See
    ``backtest_sweep.get_sweep`` for the rationale.
    """
    sql = """
        SELECT
            walk_forward_id,
            user_id,
            search_type,
            search_spec,
            select_metric,
            maximize,
            refit,
            status,
            total_windows,
            completed_windows,
            failed_windows,
            mean_validation_metric,
            summary_json,
            created_at,
            completed_at,
            updated_at
        FROM backtest.backtest_walk_forwards
        WHERE walk_forward_id = %(walk_forward_id)s
    """
    async with db.cursor() as cur:
        await cur.execute(sql, {"walk_forward_id": walk_forward_id})
        row = await cur.fetchone()

    if row is None or row["user_id"] != user_id:
        raise NotFound(f"walk-forward not found: {walk_forward_id}")
    job_row = await _JOB_STORE.get_job_by_ref_id(walk_forward_id, user_id=user_id, conn=db)
    return _walk_forward_detail(row, job_row)


async def stream_walk_forward_events(
    *,
    walk_forward_id: str,
    user_id: str,
    request: Request,
    last_event_id: str | None = None,  # noqa: ARG001  (plumbed for future event-log)
) -> AsyncIterator[bytes]:
    """Yield SSE-encoded bytes for one walk-forward study's lifecycle.

    Mirrors :func:`backtest_sweep.stream_sweep_events`: the wire
    format is ``snapshot`` → ``update`` * N → ``done``, and the
    ``data:`` payload is the :func:`_walk_forward_detail` of the
    walk-forward row with the parent job merged in for live
    ``progress`` / ``job_status``.

    See ``backtest_sweep.stream_sweep_events`` for the full design
    rationale (terminal detection uses the parent job's status so
    cancellation surfaces correctly — the walk-forward row's own
    status enum has no ``cancelled`` value).
    """
    # 1) Initial snapshot + owner-scope check. The owner-scope SQL
    # is inlined here (rather than going through ``_WF_STORE``) so
    # we don't pay for a second round-trip in the common case.
    first_wf = await _fetch_walk_forward(
        walk_forward_id,
        user_id=user_id,
    )
    if first_wf is None:
        raise NotFound(f"walk-forward not found: {walk_forward_id}")
    first_job = await _JOB_STORE.get_job_by_ref_id(
        walk_forward_id,
        user_id=user_id,
    )
    last_payload = _walk_forward_detail(first_wf, first_job)
    snapshot_id = str(last_payload["updated_at"])
    yield _sse_frame("snapshot", last_payload, event_id=snapshot_id)

    if _is_terminal_payload(last_payload):
        yield _sse_frame("done", last_payload, event_id=snapshot_id)
        return

    last_etag = _payload_etag(last_payload)
    loop = asyncio.get_running_loop()
    next_heartbeat = loop.time() + _HEARTBEAT_INTERVAL_S

    # Round #1063 — subscribe to the listener on the parent job_id.
    # See ``backtest_sweep.stream_sweep_events`` for the rationale;
    # the walk-forward lifecycle is identical (sweep-row-only updates
    # don't exist; the parent backtest_jobs row is the carrier).
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
                wf_row = await _fetch_walk_forward(
                    walk_forward_id,
                    user_id=user_id,
                )
                job_row = await _JOB_STORE.get_job_by_ref_id(
                    walk_forward_id,
                    user_id=user_id,
                )
            except Exception:
                yield _sse_frame(
                    "error",
                    {"detail": "internal read error"},
                )
                return

            if wf_row is None:
                # Walk-forward row vanished — emit a synthetic cancelled
                # ``done`` so the page can drop into the terminal state.
                last_payload = _walk_forward_detail(
                    _empty_wf_row(walk_forward_id, last_payload),
                    job_row,
                )
                yield _sse_frame(
                    "done",
                    last_payload,
                    event_id=str(last_payload["updated_at"]),
                )
                return

            payload = _walk_forward_detail(wf_row, job_row)
            etag = _payload_etag(payload)
            now = loop.time()

            if etag == last_etag:
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


async def _fetch_walk_forward(
    walk_forward_id: str,
    *,
    user_id: str,
) -> dict[str, Any] | None:
    """Read the walk-forward row + owner-scope check.

    Returns ``None`` for missing rows AND for cross-user probes —
    callers map both to ``NotFound`` so the API never leaks
    existence.
    """
    sql = """
        SELECT
            walk_forward_id,
            user_id,
            search_type,
            search_spec,
            select_metric,
            maximize,
            refit,
            status,
            total_windows,
            completed_windows,
            failed_windows,
            mean_validation_metric,
            summary_json,
            created_at,
            completed_at,
            updated_at
        FROM backtest.backtest_walk_forwards
        WHERE walk_forward_id = %(walk_forward_id)s
    """
    # The store has a ``get_walk_forward`` method but the service
    # module already does the read inline in ``get_walk_forward``;
    # duplicating the small SQL keeps the two code paths independent
    # and avoids a tight coupling between the stream generator and
    # the (sync-shaped) read function.
    from psycopg import AsyncConnection  # noqa: F401  (typing only)

    from gr_data.db import pg_pool

    async with pg_pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(sql, {"walk_forward_id": walk_forward_id})
        row = await cur.fetchone()
    if row is None or row["user_id"] != user_id:
        return None
    return row


def _empty_wf_row(
    walk_forward_id: str,
    last_payload: dict[str, Any],
) -> dict[str, Any]:
    """Synthetic row used when the walk-forward vanishes mid-stream.

    Mirrors the fields :func:`_walk_forward_summary` reads so the
    downstream ``_walk_forward_detail`` can render a coherent
    cancelled frame without the original row.
    """
    return {
        "walk_forward_id": walk_forward_id,
        "user_id": last_payload.get("user_id"),
        "search_type": last_payload.get("search_type"),
        "search_spec": last_payload.get("search_spec"),
        "select_metric": last_payload.get("select_metric"),
        "maximize": last_payload.get("maximize"),
        "refit": last_payload.get("refit"),
        "status": "cancelled",
        "total_windows": last_payload.get("total_windows"),
        "completed_windows": last_payload.get("completed_windows"),
        "failed_windows": last_payload.get("failed_windows"),
        "mean_validation_metric": last_payload.get("mean_validation_metric"),
        "summary_json": last_payload.get("summary_json"),
        "created_at": last_payload.get("created_at"),
        "completed_at": last_payload.get("completed_at"),
        "updated_at": last_payload.get("updated_at"),
    }


async def list_windows(
    db: AsyncConnection,
    walk_forward_id: str,
    *,
    status: str | None,
    page: PageParams,
    user_id: str,
) -> tuple[list[dict[str, Any]], int]:
    """List persisted window rows for one walk-forward study owned by ``user_id``."""
    await _assert_walk_forward_owner(db, walk_forward_id, user_id)
    conds: list[str] = ["walk_forward_id = %(walk_forward_id)s"]
    params: dict[str, object] = {
        "walk_forward_id": walk_forward_id,
        "limit": page.limit,
        "offset": page.offset,
    }
    if status:
        conds.append("status = %(status)s")
        params["status"] = status

    where_sql = " AND ".join(conds)
    sql = f"""
        SELECT
            walk_forward_id,
            window_index,
            train_start,
            train_end,
            val_start,
            val_end,
            status,
            error_message,
            train_sweep_id,
            best_trial_id,
            best_run_id,
            validation_run_id,
            best_params,
            train_metric_value,
            validation_metric_value,
            validation_metrics_json,
            created_at,
            completed_at,
            updated_at,
            COUNT(*) OVER() AS _total
        FROM backtest.backtest_walk_forward_windows
        WHERE {where_sql}
        ORDER BY window_index ASC
        LIMIT %(limit)s OFFSET %(offset)s
    """
    async with db.cursor() as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()

    total = int(rows[0]["_total"]) if rows else 0
    return [_window(row) for row in rows], total


async def get_oos_equity_curve(
    db: AsyncConnection,
    walk_forward_id: str,
    *,
    user_id: str,
) -> list[dict[str, Any]]:
    """Return persisted OOS equity points for a walk-forward study owned by ``user_id``."""
    await _assert_walk_forward_owner(db, walk_forward_id, user_id)
    sql = """
        SELECT
            w.walk_forward_id,
            w.window_index,
            e.run_id,
            e.strategy_name,
            e.dt,
            e.cash,
            e.equity,
            e.trading_pnl,
            e.mtm_pnl,
            e.total_fees,
            e.gross_exposure,
            e.row_json,
            e.created_at
        FROM backtest.backtest_walk_forward_windows w
        JOIN backtest.backtest_equity_points e
            ON e.run_id = w.validation_run_id
        WHERE w.walk_forward_id = %(walk_forward_id)s
          AND w.validation_run_id IS NOT NULL
        ORDER BY w.window_index ASC, e.dt ASC, e.strategy_name ASC
    """
    async with db.cursor() as cur:
        await cur.execute(sql, {"walk_forward_id": walk_forward_id})
        rows = await cur.fetchall()
    return [_equity_point(row) for row in rows]


# ---------------------------------------------------------------- helpers


def _walk_forward_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "walk_forward_id": row["walk_forward_id"],
        "search_type": row["search_type"],
        "search_spec": _json_value(row["search_spec"], {}),
        "select_metric": row["select_metric"],
        "maximize": row["maximize"],
        "refit": row["refit"],
        "status": row["status"],
        "total_windows": row["total_windows"],
        "completed_windows": row["completed_windows"],
        "failed_windows": row["failed_windows"],
        "mean_validation_metric": _f_nullable(row["mean_validation_metric"]),
        "created_at": _dt(row["created_at"]),
        "completed_at": _dt_nullable(row["completed_at"]),
        "updated_at": _dt(row["updated_at"]),
    }


def _walk_forward_detail(
    row: dict[str, Any],
    job_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = _walk_forward_summary(row)
    data["summary_json"] = _json_value(row["summary_json"], {})
    # Job linkage — same shape as ``_sweep_detail`` so the frontend
    # can drive both pages off the same SSE wiring template. When the
    # runner has not yet claimed the job (or the job is already
    # terminal and cleaned up), the three fields are None.
    if job_row is not None:
        data["job_id"] = job_row.get("job_id")
        data["progress"] = int(job_row.get("progress") or 0)
        data["job_status"] = job_row.get("status")
    else:
        data["job_id"] = None
        data["progress"] = None
        data["job_status"] = None
    return data


def _window(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "walk_forward_id": row["walk_forward_id"],
        "window_index": row["window_index"],
        "train_start": _dt(row["train_start"]),
        "train_end": _dt(row["train_end"]),
        "val_start": _dt(row["val_start"]),
        "val_end": _dt(row["val_end"]),
        "status": row["status"],
        "error_message": row["error_message"],
        "train_sweep_id": row["train_sweep_id"],
        "best_trial_id": row["best_trial_id"],
        "best_run_id": row["best_run_id"],
        "validation_run_id": row["validation_run_id"],
        "best_params": _json_value(row["best_params"], {}),
        "train_metric_value": _f_nullable(row["train_metric_value"]),
        "validation_metric_value": _f_nullable(row["validation_metric_value"]),
        "validation_metrics_json": _json_value(row["validation_metrics_json"], {}),
        "created_at": _dt(row["created_at"]),
        "completed_at": _dt_nullable(row["completed_at"]),
        "updated_at": _dt(row["updated_at"]),
    }


def _equity_point(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "walk_forward_id": row["walk_forward_id"],
        "window_index": row["window_index"],
        "run_id": row["run_id"],
        "strategy_name": row["strategy_name"],
        "dt": _dt(row["dt"]),
        "cash": _f_nullable(row["cash"]),
        "equity": _f(row["equity"]),
        "trading_pnl": _f_nullable(row["trading_pnl"]),
        "mtm_pnl": _f_nullable(row["mtm_pnl"]),
        "total_fees": _f_nullable(row["total_fees"]),
        "gross_exposure": _f_nullable(row["gross_exposure"]),
        "row_json": _json_value(row["row_json"], {}),
        "created_at": _dt(row["created_at"]),
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


# ---------------------------------------------------------------- stream helpers


def _is_terminal_payload(payload: dict[str, Any]) -> bool:
    """True if the SSE payload reflects a finished walk-forward.

    Mirrors :func:`backtest_sweep._is_terminal_payload` — key on the
    parent job's status (which includes ``cancelled``) so
    cancellation surfaces correctly.
    """
    job_status = payload.get("job_status")
    if job_status is not None:
        return job_status in _TERMINAL_STATUSES
    wf_status = payload.get("status")
    return wf_status in {"completed", "failed"}


def _payload_etag(payload: dict[str, Any]) -> tuple[Any, ...]:
    """Coarse de-dup key for SSE updates.

    Two payloads with the same etag do not need a re-emit. The
    tuple covers the live-status surface that the page renders;
    ``summary_json`` changes don't trigger a frame.
    """
    return (
        payload.get("status"),
        payload.get("job_status"),
        payload.get("progress"),
        payload.get("updated_at"),
    )
