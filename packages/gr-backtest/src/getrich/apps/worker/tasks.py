"""Celery task definitions for the backtest worker pool.

Three top-level Celery tasks — one per job type — each wraps the
shared ``_run_job_sync`` helper that:

1. Looks up the job in PostgreSQL via :class:`PgBacktestJobStore`.
2. Picks the right op via :func:`get_op_for_job_type` (backtest /
   sweep / walk_forward).
3. Builds a :class:`BacktestJobRunner` and drives a single iteration
   via ``asyncio.run(runner.run_once())``.

The three task names are stable identifiers the API process sends
to via ``app.send_task("backtest.run_job", args=[job_id])``. The
``job_type`` is the source of truth, not the task name; the API
dispatcher explicitly passes the right task name per endpoint, so a
rename here ripples through the three POST handlers in
:mod:`getrich.apps.web.routers.backtest_jobs`.

Concurrency model: ``worker_prefetch_multiplier=1`` (set in
:mod:`getrich.apps.worker.celery_app`) means each worker child
process holds at most one task in memory at a time. Long-running
backtests don't starve shorter ones.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from celery import shared_task

# Round #1204 (Tier 1): the worker spawns fresh asyncio.run() loops
# per task. On Windows those default to ProactorEventLoop, which
# psycopg3 rejects at first await. We force SelectorEventLoop
# globally before any task body runs. POSIX is untouched.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from getrich.apps.strategy.backtest_job_runner import BacktestJobRunner
from getrich.apps.strategy.ops import get_op_for_job_type
from getrich.apps.worker.lifespan import (
    close_cancel_listener,
    close_pg_pool,
    init_cancel_listener,
    init_pg_pool,
)
from gr_data.config.settings import make_pg_dsn, settings
from getrich_backtest.job_persistence import PgBacktestJobStore


logger = logging.getLogger(__name__)


# Sentinel for "no owner scoping" — used by the runner to read any
# user's job. The runner lives outside the user request context.
_SYSTEM_USER_ID = "*"

# Module-level store: PgBacktestJobStore() with default global pool.
# Pool is opened per worker process via init_pg_pool() below.
_STORE = PgBacktestJobStore()


def _run_job_sync(job_id: str) -> dict[str, Any]:
    """Run a single backtest_jobs row to completion.

    The Celery task body is sync. The runner is async, so we drive
    it with ``asyncio.run`` in a fresh loop. The pool is opened and
    closed around the runner call so a failed task doesn't leak
    pool resources on a long-lived worker child.

    Round #1080 P0.1: also opens/closes the
    :class:`WorkerCancelListener` so the per-trial ``is_cancelled``
    probe is push-driven (in-memory) instead of a per-trial DB
    read. The listener is best-effort — if ``start()`` fails, the
    probe falls back to the DB read on every trial (still correct,
    just slower).

    Parameters
    ----------
    job_id : str
        The ``backtest_jobs.job_id`` to execute.

    Returns
    -------
    dict
        ``BacktestJobRunResult.to_dict()`` payload — ``claimed``,
        ``job_id``, ``final_status``, ``error``.
    """
    init_pg_pool()
    init_cancel_listener()
    try:

        async def _go() -> dict[str, Any]:
            row = await _STORE.get_job(job_id, user_id=_SYSTEM_USER_ID)
            if row is None:
                logger.warning("worker received job_id=%s but row not found", job_id)
                return {
                    "claimed": False,
                    "job_id": job_id,
                    "final_status": None,
                    "error": "job not found",
                }
            op = get_op_for_job_type(row["job_type"])
            runner = BacktestJobRunner(
                _STORE,
                op,
                job_type=row["job_type"],
                sleep_seconds=0,
                db_conninfo=make_pg_dsn(settings.postgres),
            )
            result = await runner.run_once()
            return result.to_dict()

        return asyncio.run(_go())
    finally:
        close_cancel_listener()
        close_pg_pool()


# Three top-level Celery tasks. ``bind=True`` so the task instance is
# the first arg, in case we want ``self.retry(...)`` later; we don't
# use it now because the runner already implements the DB-backed
# retry / ``max_attempts`` policy (Phase 0 of this round explicitly
# did not want to mix Celery's ``max_retries`` with the store's
# ``max_attempts`` — they're different concepts).


@shared_task(name="backtest.run_job", bind=True, max_retries=None)
def run_backtest_job(self: Any, job_id: str) -> dict[str, Any]:
    """Run a queued backtest job to completion."""
    return _run_job_sync(job_id)


@shared_task(name="sweep.run_job", bind=True, max_retries=None)
def run_sweep_job(self: Any, job_id: str) -> dict[str, Any]:
    """Run a queued sweep job to completion."""
    return _run_job_sync(job_id)


@shared_task(name="walk_forward.run_job", bind=True, max_retries=None)
def run_walk_forward_job(self: Any, job_id: str) -> dict[str, Any]:
    """Run a queued walk-forward job to completion."""
    return _run_job_sync(job_id)
