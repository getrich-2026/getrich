"""PostgreSQL persistence for backtest job lifecycle tracking.

The job table is intentionally business/task-orchestration data, so it lives
exclusively in PostgreSQL. ClickHouse/DuckDB are not involved here.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from gr_data.db.pool import PgConnectionPool, pg_pool


if TYPE_CHECKING:
    from psycopg import AsyncConnection


_JOB_STATUS_VALUES = frozenset({"queued", "running", "completed", "failed", "cancelled"})
_JOB_TYPE_VALUES = frozenset({"backtest", "sweep", "walk_forward"})

# Sentinel used by internal callers (runner, recovery) to indicate
# "do not filter by user_id" when invoking owner-scoped read APIs. The
# store treats ``"*"`` as the explicit "system role" override.
_SYSTEM_USER = "*"


class BacktestJobError(Exception):
    """Raised when a backtest job cannot be persisted or transitioned."""


class PgBacktestJobStore:
    """PostgreSQL-backed store for backtest job lifecycle rows."""

    def __init__(self, pool: PgConnectionPool | None = None) -> None:
        self._pool = pool or pg_pool

    async def create_job(
        self,
        job_type: str,
        ref_id: str,
        *,
        request_json: Mapping[str, object] | None = None,
        request_hash: str | None = None,
        max_attempts: int = 1,
        user_id: str | None = None,
        retry_base_seconds: float | None = None,
        retry_cap_seconds: float | None = None,
        retry_jitter_pct: float | None = None,
        conn: AsyncConnection | None = None,
    ) -> str:
        """Insert a new ``queued`` job and return its generated ``job_id``."""
        if job_type not in _JOB_TYPE_VALUES:
            valid = ", ".join(sorted(_JOB_TYPE_VALUES))
            raise ValueError(f"job_type must be one of: {valid}")
        if not ref_id.strip():
            raise ValueError("ref_id must be non-empty")
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        # ``request_hash`` is the sha256-hex of the canonical request body,
        # computed by the service layer. Defensive shape check so a bogus
        # string never reaches the CHAR(64) column.
        if request_hash is not None:
            if not isinstance(request_hash, str) or len(request_hash) != 64:
                raise ValueError("request_hash must be a 64-char sha256 hex string")
            try:
                int(request_hash, 16)
            except ValueError as exc:
                raise ValueError("request_hash must be a 64-char sha256 hex string") from exc
        # Per-job retry overrides: each must be a finite, non-negative
        # number; the cross-field ``cap >= base`` invariant is the
        # caller's responsibility (the Pydantic layer enforces it).
        for name, value in (
            ("retry_base_seconds", retry_base_seconds),
            ("retry_cap_seconds", retry_cap_seconds),
            ("retry_jitter_pct", retry_jitter_pct),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative when provided")
        if (
            retry_base_seconds is not None
            and retry_cap_seconds is not None
            and retry_cap_seconds < retry_base_seconds
        ):
            raise ValueError("retry_cap_seconds must be >= retry_base_seconds")

        job_id = uuid4().hex
        # Strip the legacy ``_user_id`` key from the JSONB payload — owner is
        # now a first-class column on the row.
        payload: dict[str, object] = dict(request_json) if request_json else {}
        payload.pop("_user_id", None)
        request_payload = _json_dumps(payload)

        async def op(db: AsyncConnection) -> None:
            async with db.cursor() as cur:
                await cur.execute(
                    _INSERT_JOB_SQL,
                    {
                        "job_id": job_id,
                        "job_type": job_type,
                        "ref_id": ref_id,
                        "request_json": request_payload,
                        "request_hash": request_hash,
                        "max_attempts": max_attempts,
                        "user_id": user_id,
                        "retry_base_seconds": retry_base_seconds,
                        "retry_cap_seconds": retry_cap_seconds,
                        "retry_jitter_pct": retry_jitter_pct,
                    },
                )
                # No NOTIFY here: at enqueue time the SSE subscriber
                # does not exist yet — the client just received the
                # ``job_id`` in the POST response and will open the
                # stream on the next page render, which re-reads the
                # row as the initial snapshot. (Round #1063 trade-off.)

        try:
            await self._run(op, conn=conn)
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, BacktestJobError):
                raise
            raise BacktestJobError(f"failed to create job for {job_type} {ref_id!r}") from exc
        return job_id

    async def claim_next_queued(
        self,
        job_type: str,
        *,
        conn: AsyncConnection | None = None,
        stale_seconds: int = 300,
    ) -> dict[str, Any] | None:
        """Atomically claim the next runnable job of *job_type* and mark it running.

        Two candidate pools are considered, in priority order:

        1. ``status='queued'`` rows whose ``next_retry_at`` is due (the normal
           pending-queue path).
        2. ``status='running'`` rows whose ``updated_at`` is older than
           ``stale_seconds`` ago (P2 #311 stuck-running recovery: a worker
           crashed mid-job and another worker is reclaiming the row).

        Uses ``FOR UPDATE SKIP LOCKED`` inside the CTE so multiple workers
        may call this safely. Returns the claimed row, or ``None`` if no
        runnable job is available.

        The returned row carries a synthetic boolean field
        ``_was_recovered`` which is ``True`` only when the picked row was
        previously ``running`` (i.e., this is a recovery, not a fresh
        claim). The runner can use this flag to log the recovery.
        """
        if job_type not in _JOB_TYPE_VALUES:
            valid = ", ".join(sorted(_JOB_TYPE_VALUES))
            raise ValueError(f"job_type must be one of: {valid}")
        if stale_seconds < 0:
            raise ValueError("stale_seconds must be non-negative")

        async def op(db: AsyncConnection) -> dict[str, Any] | None:
            async with db.cursor() as cur:
                await cur.execute(
                    _CLAIM_NEXT_JOB_SQL,
                    {"job_type": job_type, "stale_seconds": stale_seconds},
                )
                row = await cur.fetchone()
            if row is None:
                return None
            was_recovered = row["status"] == "running"
            async with db.cursor() as cur:
                await cur.execute(
                    _RESET_RUNNING_SQL,
                    {"job_id": row["job_id"]},
                )
            row["status"] = "running"
            row["started_at"] = _now_shanghai()
            row["_was_recovered"] = was_recovered
            # Pydantic 2.5+ Decimal/aware-datetime JSONB columns decode as str;
            # convert the retry timestamp to a Python datetime for the runner.
            nra = row.get("next_retry_at")
            if isinstance(nra, str):
                from datetime import datetime as _dt

                row["next_retry_at"] = _dt.fromisoformat(nra)
            return row

        try:
            return await self._run(op, conn=conn, commit=False)
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, BacktestJobError):
                raise
            raise BacktestJobError(
                f"failed to claim next queued job for type {job_type!r}"
            ) from exc

    async def mark_running(
        self,
        job_id: str,
        *,
        conn: AsyncConnection | None = None,
    ) -> bool:
        """Transition ``queued`` → ``running``. Returns ``True`` on success."""

        async def op(db: AsyncConnection) -> bool:
            async with db.cursor() as cur:
                await cur.execute(
                    _MARK_RUNNING_SQL,
                    {"job_id": job_id},
                )
                changed = cur.rowcount > 0
                if changed:
                    # Same transaction — NOTIFY is buffered until COMMIT.
                    await cur.execute(_NOTIFY_JOB_SQL, {"job_id": job_id})
                return changed

        try:
            return await self._run(op, conn=conn, commit=False)
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, BacktestJobError):
                raise
            raise BacktestJobError(f"failed to mark job {job_id!r} as running") from exc

    async def update_progress(
        self,
        job_id: str,
        progress: int,
        *,
        conn: AsyncConnection | None = None,
    ) -> bool:
        """Update progress (clamped 0-100) for an active job."""

        clamped = max(0, min(100, int(progress)))

        async def op(db: AsyncConnection) -> None:
            async with db.cursor() as cur:
                await cur.execute(
                    _UPDATE_PROGRESS_SQL,
                    {"job_id": job_id, "progress": clamped},
                )
                # Same transaction as the UPDATE — throttled to ≤ 21
                # notifications per job by the runner's 5%-boundary
                # check, so this stays well within PostgreSQL's NOTIFY
                # rate budget.
                await cur.execute(_NOTIFY_JOB_SQL, {"job_id": job_id})

        try:
            await self._run(op, conn=conn, commit=False)
            return True
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, BacktestJobError):
                raise
            raise BacktestJobError(f"failed to update progress for job {job_id!r}") from exc

    async def mark_completed(
        self,
        job_id: str,
        *,
        conn: AsyncConnection | None = None,
    ) -> bool:
        """Transition ``running`` → ``completed``. Returns ``True`` on success."""

        async def op(db: AsyncConnection) -> None:
            async with db.cursor() as cur:
                await cur.execute(
                    _MARK_COMPLETED_SQL,
                    {"job_id": job_id},
                )
                # Same transaction as the UPDATE — the SSE listener
                # wakes the page within ~10ms of completion.
                await cur.execute(_NOTIFY_JOB_SQL, {"job_id": job_id})

        try:
            await self._run(op, conn=conn, commit=False)
            return True
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, BacktestJobError):
                raise
            raise BacktestJobError(f"failed to mark job {job_id!r} as completed") from exc

    async def mark_failed(
        self,
        job_id: str,
        error_message: str,
        *,
        conn: AsyncConnection | None = None,
    ) -> bool:
        """Transition to ``failed`` from any non-terminal state."""

        async def op(db: AsyncConnection) -> None:
            async with db.cursor() as cur:
                await cur.execute(
                    _MARK_FAILED_SQL,
                    {"job_id": job_id, "error_message": error_message},
                )
                # Same transaction as the UPDATE — terminal transition
                # wakes the SSE listener immediately.
                await cur.execute(_NOTIFY_JOB_SQL, {"job_id": job_id})

        try:
            await self._run(op, conn=conn, commit=False)
            return True
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, BacktestJobError):
                raise
            raise BacktestJobError(f"failed to mark job {job_id!r} as failed") from exc

    async def mark_retry(
        self,
        job_id: str,
        *,
        error_message: str,
        next_retry_at: datetime,
        conn: AsyncConnection | None = None,
    ) -> bool:
        """Re-queue a job that failed transiently.

        Resets ``status='queued'`` and ``progress=0`` so the row is
        immediately re-claimable once ``next_retry_at`` is reached;
        bumps ``attempt`` by 1; preserves the ``error_message`` for
        observability. ``started_at`` and ``completed_at`` are cleared
        so a future claim behaves like a fresh run.
        """

        async def op(db: AsyncConnection) -> None:
            async with db.cursor() as cur:
                await cur.execute(
                    _MARK_RETRY_SQL,
                    {
                        "job_id": job_id,
                        "error_message": error_message,
                        "next_retry_at": next_retry_at,
                    },
                )
                # Same transaction as the UPDATE — re-queued jobs
                # wake the SSE listener so the page can re-render the
                # backoff countdown without waiting 1s.
                await cur.execute(_NOTIFY_JOB_SQL, {"job_id": job_id})

        try:
            await self._run(op, conn=conn, commit=False)
            return True
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, BacktestJobError):
                raise
            raise BacktestJobError(f"failed to mark job {job_id!r} for retry") from exc

    async def get_by_idempotency_key(
        self,
        *,
        key: str,
        user_id: str | None = None,
        conn: AsyncConnection | None = None,
    ) -> dict[str, Any] | None:
        """Look up a job by ``request_json._idempotency_key``.

        Scoped by the row's ``user_id`` so cross-tenant collisions do not
        return the wrong job. When ``user_id`` is the system sentinel
        ``"*"`` or is omitted, owner scoping is disabled (the latest
        matching row is returned). Pass an actual user id to enforce
        owner scoping.
        """

        async def op(db: AsyncConnection) -> dict[str, Any] | None:
            async with db.cursor() as cur:
                await cur.execute(
                    _SELECT_BY_IDEMPOTENCY_KEY_SQL,
                    {"key": key, "user_id": user_id},
                )
                return await cur.fetchone()

        try:
            return await self._run(op, conn=conn, commit=False)
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, BacktestJobError):
                raise
            raise BacktestJobError("failed to look up job by idempotency key") from exc

    async def mark_cancelled(
        self,
        job_id: str,
        *,
        user_id: str | None = None,
        conn: AsyncConnection | None = None,
    ) -> bool:
        """Transition ``queued`` or ``running`` → ``cancelled``.

        When ``user_id`` is provided, only cancel rows owned by that user
        (or unowned ``NULL`` rows, if the caller passes ``user_id=None``
        explicitly to indicate the system role). Returns ``False`` when no
        matching row was updated; idempotent on already-cancelled jobs.
        """

        async def op(db: AsyncConnection) -> bool:
            async with db.cursor() as cur:
                await cur.execute(
                    _MARK_CANCELLED_SQL,
                    {"job_id": job_id, "user_id": user_id},
                )
                changed = cur.rowcount > 0
            if changed:
                # Separate cursor block: NOTIFY outside the UPDATE
                # cursor so a no-op cancel (already-cancelled job,
                # rowcount=0) does not produce a spurious wake-up.
                async with db.cursor() as cur:
                    await cur.execute(_NOTIFY_JOB_SQL, {"job_id": job_id})
            return changed

        try:
            return await self._run(op, conn=conn, commit=False)
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, BacktestJobError):
                raise
            raise BacktestJobError(f"failed to mark job {job_id!r} as cancelled") from exc

    async def get_job(
        self,
        job_id: str,
        *,
        user_id: str | None = None,
        conn: AsyncConnection | None = None,
    ) -> dict[str, Any] | None:
        """Return one job row, or ``None`` if missing or not owned by ``user_id``.

        When ``user_id`` is ``None`` (sentinel: "filter not requested"),
        the query returns the row regardless of owner. When ``user_id``
        is the string ``"*"``, the query also returns the row regardless
        of owner — this is a system/internal mode used by the runner.
        Pass an actual user id to enforce owner scoping.
        """

        async def op(db: AsyncConnection) -> dict[str, Any] | None:
            async with db.cursor() as cur:
                await cur.execute(
                    _SELECT_JOB_SQL,
                    {"job_id": job_id, "user_id": user_id},
                )
                return await cur.fetchone()

        try:
            return await self._run(op, conn=conn, commit=False)
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, BacktestJobError):
                raise
            raise BacktestJobError(f"failed to load job {job_id!r}") from exc

    async def get_job_by_ref_id(
        self,
        ref_id: str,
        *,
        user_id: str | None = None,
        conn: AsyncConnection | None = None,
    ) -> dict[str, Any] | None:
        """Return the most recent job row whose ``ref_id`` matches.

        Mirrors :meth:`get_job`'s owner-scope contract verbatim: pass
        ``None`` or ``"*"`` to disable filtering, pass an actual user id
        to enforce ``user_id IS NOT DISTINCT FROM``. Returns ``None`` for
        missing rows and for cross-user probes that match no owned row.

        ``ref_id`` is not declared ``UNIQUE`` on the schema (a retried
        ``sweep`` may create multiple rows with the same ``ref_id``), so
        the query orders by ``created_at DESC`` and takes ``LIMIT 1``.
        Callers that need a canonical id should use the ``job_id``
        returned by ``create_*_job``; this lookup is intended for
        client-side correlation (e.g. ``GET /backtest-sweeps/{sweep_id}``
        needs to find the parent job so the frontend can open the
        ``/backtest-jobs/{job_id}/events`` SSE stream).
        """

        async def op(db: AsyncConnection) -> dict[str, Any] | None:
            async with db.cursor() as cur:
                await cur.execute(
                    _SELECT_JOB_BY_REF_ID_SQL,
                    {"ref_id": ref_id, "user_id": user_id},
                )
                return await cur.fetchone()

        try:
            return await self._run(op, conn=conn, commit=False)
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, BacktestJobError):
                raise
            raise BacktestJobError(f"failed to load job by ref_id {ref_id!r}") from exc

    async def list_jobs(
        self,
        *,
        job_type: str | None = None,
        status: str | None = None,
        user_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        conn: AsyncConnection | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """List jobs with optional filters; returns ``(rows, total)``.

        When ``user_id`` is provided, the query is restricted to rows
        owned by that user. When ``user_id`` is the system sentinel
        ``"*"``, ownership is not filtered.
        """
        if job_type is not None and job_type not in _JOB_TYPE_VALUES:
            valid = ", ".join(sorted(_JOB_TYPE_VALUES))
            raise ValueError(f"job_type must be one of: {valid}")
        if status is not None and status not in _JOB_STATUS_VALUES:
            valid = ", ".join(sorted(_JOB_STATUS_VALUES))
            raise ValueError(f"status must be one of: {valid}")
        if limit <= 0:
            raise ValueError("limit must be positive")
        if offset < 0:
            raise ValueError("offset must be non-negative")

        conds: list[str] = ["TRUE"]
        params: dict[str, object] = {"limit": limit, "offset": offset}
        if job_type is not None:
            conds.append("job_type = %(job_type)s")
            params["job_type"] = job_type
        if status is not None:
            conds.append("status = %(status)s")
            params["status"] = status
        if user_id is not None and user_id != _SYSTEM_USER:
            conds.append("user_id IS NOT DISTINCT FROM %(user_id)s")
            params["user_id"] = user_id
        where_sql = " AND ".join(conds)
        sql = f"""
            SELECT *, COUNT(*) OVER() AS _total
            FROM backtest.backtest_jobs
            WHERE {where_sql}
            ORDER BY created_at DESC, job_id DESC
            LIMIT %(limit)s OFFSET %(offset)s
        """

        async def op(db: AsyncConnection) -> tuple[list[dict[str, Any]], int]:
            async with db.cursor() as cur:
                await cur.execute(sql, params)
                rows = await cur.fetchall()
            total = int(rows[0]["_total"]) if rows else 0
            for row in rows:
                row.pop("_total", None)
            return rows, total

        try:
            return await self._run(op, conn=conn, commit=False)
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, BacktestJobError):
                raise
            raise BacktestJobError("failed to list backtest jobs") from exc

    async def _run(
        self,
        op: Callable[[AsyncConnection], Awaitable[Any]],
        *,
        conn: AsyncConnection | None,
        commit: bool = True,
    ) -> Any:
        if conn is not None:
            return await op(conn)
        async with self._pool.connection() as owned:
            result = await op(owned)
            if commit:
                await owned.commit()
            return result


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"object of type {type(value).__name__} is not JSON serializable")


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=_json_default, separators=(",", ":"))


# Late import to avoid circular import with time module.
def _now_shanghai() -> datetime:
    """Return a Shanghai-aware datetime for fallback started_at values."""
    # Local import keeps get_shanghai_tz out of the module load path; it is
    # cheap and used only on the rare row with NULL started_at.
    from getrich_backtest.time import get_shanghai_tz

    return datetime.now(get_shanghai_tz())


_INSERT_JOB_SQL = """
INSERT INTO backtest.backtest_jobs (
    job_id, job_type, ref_id, status, request_json, request_hash, progress,
    max_attempts, user_id,
    retry_base_seconds, retry_cap_seconds, retry_jitter_pct,
    created_at, updated_at
) VALUES (
    %(job_id)s, %(job_type)s, %(ref_id)s, 'queued',
    %(request_json)s::jsonb, %(request_hash)s, 0, %(max_attempts)s, %(user_id)s,
    %(retry_base_seconds)s, %(retry_cap_seconds)s, %(retry_jitter_pct)s,
    NOW(), NOW()
)
"""

_CLAIM_NEXT_JOB_SQL = """
WITH candidate AS (
    SELECT job_id, job_type, ref_id, status, request_json, progress,
           error_message, attempt, max_attempts, next_retry_at,
           retry_base_seconds, retry_cap_seconds, retry_jitter_pct,
           created_at, started_at, completed_at, updated_at
    FROM backtest.backtest_jobs
    WHERE job_type = %(job_type)s
      AND (
          (status = 'queued'
           AND (next_retry_at IS NULL OR next_retry_at <= NOW()))
          OR
          (status = 'running'
           AND updated_at < NOW() - (%(stale_seconds)s || ' seconds')::interval)
      )
    ORDER BY
        CASE WHEN status = 'queued' THEN 0 ELSE 1 END ASC,
        next_retry_at NULLS FIRST,
        updated_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
SELECT job_id, job_type, ref_id, status, request_json, progress,
       error_message, attempt, max_attempts, next_retry_at,
       retry_base_seconds, retry_cap_seconds, retry_jitter_pct,
       created_at, started_at, completed_at, updated_at
FROM candidate
"""

_MARK_RUNNING_SQL = """
UPDATE backtest.backtest_jobs
SET status = 'running',
    started_at = NOW(),
    updated_at = NOW()
WHERE job_id = %(job_id)s
  AND status = 'queued'
"""

_RESET_RUNNING_SQL = """
UPDATE backtest.backtest_jobs
SET status = 'running',
    started_at = NOW(),
    updated_at = NOW()
WHERE job_id = %(job_id)s
  AND status IN ('queued', 'running')
"""

_UPDATE_PROGRESS_SQL = """
UPDATE backtest.backtest_jobs
SET progress = %(progress)s,
    updated_at = NOW()
WHERE job_id = %(job_id)s
  AND status = 'running'
"""

_MARK_COMPLETED_SQL = """
UPDATE backtest.backtest_jobs
SET status = 'completed',
    progress = 100,
    completed_at = NOW(),
    updated_at = NOW()
WHERE job_id = %(job_id)s
  AND status = 'running'
"""

_MARK_FAILED_SQL = """
UPDATE backtest.backtest_jobs
SET status = 'failed',
    error_message = %(error_message)s,
    completed_at = NOW(),
    updated_at = NOW()
WHERE job_id = %(job_id)s
  AND status IN ('queued', 'running')
"""

_MARK_CANCELLED_SQL = """
UPDATE backtest.backtest_jobs
SET status = 'cancelled',
    completed_at = NOW(),
    updated_at = NOW()
WHERE job_id = %(job_id)s
  AND status IN ('queued', 'running')
  AND (
      %(user_id)s::text = '*'
      OR user_id IS NOT DISTINCT FROM %(user_id)s
  )
"""

_SELECT_JOB_SQL = """
SELECT job_id, job_type, ref_id, status, request_json, progress,
       error_message, attempt, max_attempts, next_retry_at, user_id,
       retry_base_seconds, retry_cap_seconds, retry_jitter_pct,
       created_at, started_at, completed_at, updated_at
FROM backtest.backtest_jobs
WHERE job_id = %(job_id)s
  AND (
      %(user_id)s::text = '*'
      OR user_id IS NOT DISTINCT FROM %(user_id)s
  )
"""


_SELECT_JOB_BY_REF_ID_SQL = """
SELECT job_id, job_type, ref_id, status, request_json, request_hash, progress,
       error_message, attempt, max_attempts, next_retry_at, user_id,
       retry_base_seconds, retry_cap_seconds, retry_jitter_pct,
       created_at, started_at, completed_at, updated_at
FROM backtest.backtest_jobs
WHERE ref_id = %(ref_id)s
  AND (
      %(user_id)s::text = '*'
      OR user_id IS NOT DISTINCT FROM %(user_id)s
  )
ORDER BY created_at DESC
LIMIT 1
"""


_MARK_RETRY_SQL = """
UPDATE backtest.backtest_jobs
SET status = 'queued',
    progress = 0,
    error_message = %(error_message)s,
    attempt = attempt + 1,
    next_retry_at = %(next_retry_at)s,
    started_at = NULL,
    completed_at = NULL,
    updated_at = NOW()
WHERE job_id = %(job_id)s
"""


_SELECT_BY_IDEMPOTENCY_KEY_SQL = """
SELECT job_id, job_type, ref_id, status, request_json, request_hash, progress,
       error_message, attempt, max_attempts, next_retry_at, user_id,
       retry_base_seconds, retry_cap_seconds, retry_jitter_pct,
       created_at, started_at, completed_at, updated_at
FROM backtest.backtest_jobs
WHERE request_json->>'_idempotency_key' = %(key)s
  AND (
      %(user_id)s::text = '*'
      OR user_id IS NOT DISTINCT FROM %(user_id)s
  )
ORDER BY created_at DESC
LIMIT 1
"""


# Round #1063 — cross-process wakeup. The web process owns a long-lived
# ``LISTEN backtest_job_changed`` connection (see
# ``getrich.apps.web.services.job_listener``). Each state-mutating
# ``op()`` body appends this ``SELECT pg_notify(...)`` inside the same
# transaction as the UPDATE, so the notification is buffered by
# PostgreSQL until COMMIT — listeners wake up only after the new row
# state is visible, eliminating the worker → SSE race that a pure
# 1s polling loop suffers from. Skipped on ``create_job`` and
# ``claim_next_queued`` (no SSE subscriber yet at enqueue time, and
# the claiming worker is the only process that needs the row at that
# instant). The runner's 5%-boundary throttle caps the volume of
# ``update_progress`` notifications at ≤ 21 per job.
_NOTIFY_JOB_SQL = "SELECT pg_notify('backtest_job_changed', %(job_id)s)"


__all__ = [
    "BacktestJobError",
    "PgBacktestJobStore",
    "sync_is_cancelled_status",
]


def sync_is_cancelled_status(job_id: str, *, conninfo: str) -> bool:
    """Sync DB probe: True iff ``backtest_jobs.status == 'cancelled'``.

    Used by the worker thread's per-trial ``is_cancelled`` probe when
    the runner lives in a separate process from the API request that
    initiated the cancel. The async pool that
    :class:`PgBacktestJobStore` borrows from is not available in the
    worker's sync task body, so we open a short-lived sync psycopg
    connection and run a single ``SELECT status`` with
    ``autocommit=True`` — no transaction bookkeeping required.

    Failure mode is **fail-open**: a DB error returns ``False`` so a
    transient outage does not abort a healthy job. The runner's
    per-trial probe is best-effort; cancellation will be observed on
    the *next* trial boundary (typically ≤1s) once the DB recovers.

    Parameters
    ----------
    job_id : str
        The ``backtest_jobs.job_id`` to probe.
    conninfo : str
        A libpq DSN (e.g. from
        :func:`gr_data.config.settings.make_pg_dsn`).

    Returns
    -------
    bool
        ``True`` iff the row exists and its status is exactly
        ``"cancelled"``. ``False`` for any other status, missing
        row, or DB read error.
    """
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - guard for minimal envs
        raise RuntimeError(
            "psycopg (sync) is required for sync_is_cancelled_status; install psycopg[binary]"
        ) from exc
    try:
        with psycopg.connect(conninfo, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM backtest.backtest_jobs WHERE job_id = %s",
                (job_id,),
            )
            row = cur.fetchone()
    except Exception:  # noqa: BLE001 - fail-open per contract above
        return False
    return row is not None and row[0] == "cancelled"
