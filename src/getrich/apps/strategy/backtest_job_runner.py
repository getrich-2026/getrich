"""Backtest job runner — minimal in-process executor for ``backtest_jobs``.

This module provides the smallest viable runner that:

1. Claims a queued job of a given ``job_type`` from PostgreSQL.
2. Marks it as ``running``.
3. Invokes a caller-supplied ``BacktestJobOp`` (or the default no-op).
4. Marks the job ``completed``, ``failed``, or leaves it ``cancelled`` based
   on the outcome.

P0 does not implement real backtest / sweep / walk-forward execution: callers
inject their own ``op`` to plug into the runner. The default ``BacktestOneShotOp``
just sleeps briefly to demonstrate the lifecycle.

P1 wires two cooperating hooks: when a job is claimed, the runner augments the
row dict with three keys the op can read:

* ``_progress_cb``: an async callable ``async def cb(pct: int) -> None`` that
  writes a clamped 0-100 progress value to ``backtest_jobs.progress``. Errors
  inside the callback are swallowed and logged so a flaky DB cannot interrupt
  the execution loop.
* ``_event_loop``: the runner's running event loop. Ops that need to call
  async code from a sync context (e.g. ``SweepRunner`` running inside the
  op) use this to schedule coroutines via
  ``asyncio.run_coroutine_threadsafe``.
* ``_is_cancelled``: a sync callable ``() -> bool`` that probes the DB row
  status. The runner constructs a closure over
  :func:`getrich_backtest.job_persistence.sync_is_cancelled_status` so
  workers running in a separate process from the API still observe a
  ``POST /backtest-jobs/{id}/cancel`` within a trial / window boundary
  (typically ≤1s latency).

When the op returns a dict containing ``"cancelled": True``, the runner
leaves the row in its existing ``cancelled`` state and reports
``final_status="cancelled"`` instead of calling ``mark_completed``.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from getrich_backtest.exceptions import TerminalError


if TYPE_CHECKING:
    from getrich_backtest.job_persistence import PgBacktestJobStore


logger = logging.getLogger(__name__)


@runtime_checkable
class BacktestJobOp(Protocol):
    """Callable that performs the actual work for a claimed job.

    Implementations receive the claimed job row (dict) and may return an
    optional result dict. Any exception is captured by the runner and the
    job is transitioned to ``failed`` with the error message.

    P1: the runner may inject two extra keys into ``job`` for progress
    reporting — ``_progress_cb`` (async callable) and ``_event_loop``.
    Ops may use them or ignore them; both are optional and only present
    when the runner is wired to inject them.
    """

    async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None: ...


ProgressCallback = Callable[[int], Awaitable[None]]


@dataclass(frozen=True)
class BacktestJobRunResult:
    """Summary of a single ``BacktestJobRunner.run_once()`` invocation."""

    claimed: bool
    job_id: str | None
    final_status: str | None
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "claimed": self.claimed,
            "job_id": self.job_id,
            "final_status": self.final_status,
            "error": self.error,
        }


class BacktestOneShotOp:
    """Default no-op executor that simply marks the job complete.

    Useful for smoke-testing the lifecycle and integration testing.
    """

    async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
        await asyncio.sleep(0)
        return {"progress": 100}


class BacktestJobRunner:
    """Run queued ``backtest_jobs`` to completion via the provided ``op``.

    Parameters
    ----------
    store : PgBacktestJobStore
        Persistence store for job lifecycle rows.
    op : BacktestJobOp
        Callable invoked with the claimed job row. Exceptions transition the
        job to ``failed``.
    job_type : str
        Restricts the runner to a single job category. Defaults to ``"backtest"``.
    sleep_seconds : float
        Pause between claim attempts when no job is available. Default ``1.0``.
    """

    def __init__(
        self,
        store: PgBacktestJobStore,
        op: BacktestJobOp,
        *,
        job_type: str = "backtest",
        sleep_seconds: float = 1.0,
        retry_base_seconds: float = 1.0,
        retry_cap_seconds: float = 60.0,
        retry_jitter_pct: float = 0.0,
        stale_recovery_seconds: int = 300,
        db_conninfo: str = "",
    ) -> None:
        if not callable(op):
            raise TypeError("op must be callable implementing BacktestJobOp protocol")
        if not asyncio.iscoroutinefunction(op.__call__):
            raise TypeError("op.__call__ must be a coroutine function")
        if sleep_seconds < 0:
            raise ValueError("sleep_seconds must be non-negative")
        if retry_base_seconds <= 0:
            raise ValueError("retry_base_seconds must be positive")
        if retry_cap_seconds < retry_base_seconds:
            raise ValueError("retry_cap_seconds must be >= retry_base_seconds")
        if not 0.0 <= retry_jitter_pct < 1.0:
            raise ValueError("retry_jitter_pct must be in [0.0, 1.0)")
        if stale_recovery_seconds < 0:
            raise ValueError("stale_recovery_seconds must be non-negative")
        self.store = store
        self.op = op
        self.job_type = job_type
        self.sleep_seconds = sleep_seconds
        self.retry_base_seconds = retry_base_seconds
        self.retry_cap_seconds = retry_cap_seconds
        self.retry_jitter_pct = retry_jitter_pct
        self.stale_recovery_seconds = stale_recovery_seconds
        # libpq DSN used by ``sync_is_cancelled_status`` for the per-trial
        # cancellation probe. Empty string disables the probe (the runner
        # falls back to a constant ``False``, i.e. never cancel) — used
        # by the in-process API fallback for tests / smoke.
        self.db_conninfo = db_conninfo

    async def run_once(self) -> BacktestJobRunResult:
        """Claim and execute a single queued job.

        Returns a result describing the lifecycle outcome. When no queued job
        is available, returns a result with ``claimed=False``.

        The claim path also re-claims ``running`` rows whose
        ``updated_at`` is older than ``stale_recovery_seconds`` (P2 #311
        stuck-running recovery). When a recovery happens, the runner logs
        a warning so operators can spot dead workers in production.
        """
        claimed = await self.store.claim_next_queued(
            self.job_type,
            stale_seconds=self.stale_recovery_seconds,
        )
        if claimed is None:
            await asyncio.sleep(self.sleep_seconds)
            return BacktestJobRunResult(
                claimed=False,
                job_id=None,
                final_status=None,
                error=None,
            )

        job_id = claimed["job_id"]
        attempt = int(claimed.get("attempt", 1))
        max_attempts = int(claimed.get("max_attempts", 1))
        if claimed.get("_was_recovered"):
            logger.warning(
                "backtest job %s recovered from abandoned running state "
                "(stale_recovery_seconds=%d)",
                job_id,
                self.stale_recovery_seconds,
            )
        progress_cb = self._make_progress_callback(job_id)
        loop = asyncio.get_running_loop()
        # DB-backed cancel probe. The closure calls
        # ``sync_is_cancelled_status`` which opens a short-lived sync
        # psycopg connection (autocommit) and returns True iff the row's
        # status is exactly "cancelled". An empty ``db_conninfo``
        # (e.g. the legacy in-process API fallback path) makes the
        # probe a constant ``False`` so a job that is supposed to be
        # cancellable via ``notify_job_cancelled`` in the same
        # process still works in tests that don't want DB I/O.
        is_cancelled_fn = self._make_is_cancelled_fn(job_id)
        try:
            augmented = {
                **claimed,
                "_progress_cb": progress_cb,
                "_event_loop": loop,
                "_is_cancelled": is_cancelled_fn,
            }
            result = await self.op(augmented)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "backtest job %s failed (attempt %s/%s)", job_id, attempt, max_attempts
            )
            # 1. Cancellation takes priority: if the user cancelled while the
            #    op was throwing, treat the row as cancelled — never retry
            #    a job the user explicitly asked to stop.
            if is_cancelled_fn():
                await self.store.mark_cancelled(job_id)
                return BacktestJobRunResult(
                    claimed=True,
                    job_id=job_id,
                    final_status="cancelled",
                    error=None,
                )
            # 2. P2 #314: TerminalError short-circuits the retry path. Ops
            #    signal "this is a permanent failure" by raising a
            #    TerminalError (or any subclass — e.g. ``BacktestJobError``
            #    from validation sites). The runner goes straight to
            #    ``mark_failed`` regardless of ``attempt < max_attempts``,
            #    so users with high ``max_attempts`` don't pay the
            #    backoff cost on validation errors.
            if isinstance(exc, TerminalError):
                logger.info(
                    "backtest job %s raised TerminalError (%s: %s); skipping retry path",
                    job_id,
                    type(exc).__name__,
                    exc,
                )
                await self.store.mark_failed(job_id, str(exc))
                return BacktestJobRunResult(
                    claimed=True,
                    job_id=job_id,
                    final_status="failed",
                    error=str(exc),
                )
            # 3. Retryable failure (covers RetryableError explicitly and
            #    any plain Exception by default). Honour max_attempts.
            if attempt < max_attempts:
                backoff = self._compute_backoff(attempt, claimed=claimed)
                # Lazy import to keep the runner module light when retries
                # are not in play (the common case is max_attempts=1).
                from datetime import datetime, timedelta

                from getrich_backtest.time import get_shanghai_tz

                next_retry_at = datetime.now(get_shanghai_tz()) + timedelta(seconds=backoff)
                await self.store.mark_retry(
                    job_id,
                    error_message=str(exc),
                    next_retry_at=next_retry_at,
                )
                logger.info(
                    "backtest job %s scheduled for retry attempt %s in %.1fs",
                    job_id,
                    attempt + 1,
                    backoff,
                )
                return BacktestJobRunResult(
                    claimed=True,
                    job_id=job_id,
                    final_status="failed_retryable",
                    error=str(exc),
                )
            # 4. Terminal failure (max attempts exhausted, non-TerminalError).
            await self.store.mark_failed(job_id, str(exc))
            return BacktestJobRunResult(
                claimed=True,
                job_id=job_id,
                final_status="failed",
                error=str(exc),
            )

        # Op reported cancellation: leave the row in its existing
        # ``cancelled`` status (set by ``cancel_job`` service) and report
        # ``final_status="cancelled"``. Do NOT call mark_completed.
        if isinstance(result, dict) and result.get("cancelled"):
            return BacktestJobRunResult(
                claimed=True,
                job_id=job_id,
                final_status="cancelled",
                error=None,
            )

        # If op reported progress, write it back to the row.
        if isinstance(result, dict) and "progress" in result:
            try:
                progress = int(result["progress"])
            except (TypeError, ValueError):
                progress = 100
            await self.store.update_progress(job_id, progress)

        # Race fix: ``BacktestRunOp`` calls ``Backtest(...).run()``
        # synchronously, so it cannot observe a cancel that arrives
        # mid-execution. The op will report ``{"progress": 100}`` and
        # we'd otherwise call ``mark_completed`` and overwrite the
        # already-cancelled row. Re-read the row here and respect an
        # in-flight cancel.
        if is_cancelled_fn():
            return BacktestJobRunResult(
                claimed=True,
                job_id=job_id,
                final_status="cancelled",
                error=None,
            )

        await self.store.mark_completed(job_id)
        return BacktestJobRunResult(
            claimed=True,
            job_id=job_id,
            final_status="completed",
            error=None,
        )

    def _make_is_cancelled_fn(self, job_id: str) -> Callable[[], bool]:
        """Build a ``() -> bool`` cancel probe for this job.

        When ``db_conninfo`` is set, the closure calls
        :func:`sync_is_cancelled_status` — a short-lived sync psycopg
        read against PostgreSQL. When empty (the in-process API
        fallback or a unit test), it returns a constant ``False`` so
        a job that opts out of cross-process cancellation is never
        cancelled by the probe (the op can still self-cancel via
        ``return {"cancelled": True}``).

        The closure is intentionally trivial: ops may call it from
        any thread (sync engine) or coroutine (async op).
        """
        if not self.db_conninfo:
            return lambda: False
        conninfo = self.db_conninfo
        # Lazy import to break a circular import: ``getrich.apps.strategy``
        # is imported from ``getrich_backtest.job_persistence`` via the
        # ``getrich`` package __init__ chain, so the top-level
        # ``sync_is_cancelled_status`` import would be a partial module
        # (the function lives at the bottom of job_persistence.py). The
        # function is safe to import here at call time because the
        # module is fully initialized by the time the runner runs.
        from getrich_backtest.job_persistence import sync_is_cancelled_status

        def _probe() -> bool:
            return sync_is_cancelled_status(job_id, conninfo=conninfo)

        return _probe

    def _compute_backoff(self, attempt: int, *, claimed: dict[str, Any] | None = None) -> float:
        """Exponential backoff capped at ``retry_cap_seconds``, with optional jitter.

        ``attempt`` is the just-failed attempt number (1-indexed):

        * attempt=1 → base * 2^0 = base
        * attempt=2 → base * 2
        * attempt=3 → base * 4
        * ...
        * attempt=20 → cap (2^19 * base would be huge, clamp).

        When ``retry_jitter_pct > 0``, the deterministic backoff is scaled
        by ``uniform(1 - pct, 1 + pct)`` to break thundering-herd when many
        jobs fail at the same upstream dependency simultaneously. The
        jitter is *multiplicative* and symmetric around 1.0, so the mean
        backoff is unchanged but the spread reduces synchronized retry storms.

        When ``claimed`` is provided, any of the row's
        ``retry_base_seconds`` / ``retry_cap_seconds`` / ``retry_jitter_pct``
        columns override the runner-level defaults (P1 per-job retry
        override). A NULL column falls back to the runner's default.
        """
        base_seconds = self._resolve_retry_field(
            claimed, "retry_base_seconds", self.retry_base_seconds
        )
        cap_seconds = self._resolve_retry_field(
            claimed, "retry_cap_seconds", self.retry_cap_seconds
        )
        jitter_pct = self._resolve_retry_field(claimed, "retry_jitter_pct", self.retry_jitter_pct)

        base = (
            base_seconds if attempt < 1 else min(base_seconds * (2 ** (attempt - 1)), cap_seconds)
        )
        if jitter_pct > 0.0:
            scale = random.uniform(1.0 - jitter_pct, 1.0 + jitter_pct)
            base = base * scale
        return base

    @staticmethod
    def _resolve_retry_field(
        claimed: dict[str, Any] | None,
        column: str,
        fallback: float,
    ) -> float:
        """Return the per-job override for ``column`` if present, else ``fallback``."""
        if claimed is None:
            return fallback
        value = claimed.get(column)
        if value is None:
            return fallback
        return float(value)

    def _make_progress_callback(self, job_id: str) -> ProgressCallback:
        """Return an async progress writer that swallows DB errors.

        Errors are logged at warning level but never re-raised: the op's
        primary job is to run the backtest, and a flaky progress write
        must not cascade into a job failure.

        The callback is throttled: writes only happen when the integer
        percent crosses a 5% boundary (``0, 5, 10, ..., 100``). The
        boundary check uses the **highest** boundary ever written, so
        monotonic progress yields at most 21 DB writes per job (P0
        #289-292 produced up to 1000 writes for a 1000-trial sweep) and
        out-of-order updates that don't push the boundary forward are
        dropped. Pct 100 is always flushed regardless of the boundary
        check so the row shows the final state even if a partial
        boundary write was skipped.
        """

        highest_boundary: list[int] = [-1]  # mutable cell so the closure sees updates

        async def _cb(pct: int) -> None:
            value = max(0, min(100, int(pct)))
            boundary = (value // 5) * 5
            if value != 100 and boundary <= highest_boundary[0]:
                return
            highest_boundary[0] = boundary
            try:
                await self.store.update_progress(job_id, value)
            except Exception:  # noqa: BLE001
                logger.exception("update_progress failed for job %s", job_id)

        return _cb

    async def run_until_idle(
        self,
        *,
        max_iterations: int = 10,
    ) -> list[BacktestJobRunResult]:
        """Run ``run_once`` until no queued job is available or ``max_iterations`` is reached."""
        if max_iterations <= 0:
            raise ValueError("max_iterations must be positive")
        results: list[BacktestJobRunResult] = []
        for _ in range(max_iterations):
            result = await self.run_once()
            results.append(result)
            if not result.claimed:
                break
        return results


# P3 Worker Pool round: ``notify_job_cancelled`` was the in-process
# cancellation leg for the BackgroundTasks fallback. Cancel transport
# is now DB-driven (the runner's per-trial ``_is_cancelled`` probe
# reads ``backtest_jobs.status`` via ``sync_is_cancelled_status``).
# No module-level helper is needed; ``cancel_job`` service just marks
# the row and the runner observes the new status on the next trial
# boundary (typically ≤1s). The function is intentionally absent
# from this module — tests in ``test_backtest_jobs.py`` assert that
# the service source no longer references the helper.

__all__ = [
    "BacktestJobOp",
    "BacktestJobRunResult",
    "BacktestJobRunner",
    "BacktestOneShotOp",
    "ProgressCallback",
]
