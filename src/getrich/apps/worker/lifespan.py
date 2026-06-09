"""Worker process lifespan helpers.

A Celery worker runs ``task`` functions in *worker child processes*
(many, depending on ``--concurrency``). Each child process needs:

1. A live async ``pg_pool`` (the runner uses async psycopg for its
   lifecycle writes).
2. A long-lived cancel LISTEN connection (Round #1080) so the
   runner's per-trial ``is_cancelled`` probe is push-driven
   instead of per-trial DB-read.
3. A clean teardown when the task finishes (or the worker dies).

This module exposes :func:`init_pg_pool`, :func:`close_pg_pool`,
:func:`init_cancel_listener`, and :func:`close_cancel_listener` —
small sync wrappers around the async :class:`PgConnectionPool` and
:class:`WorkerCancelListener` APIs so the Celery tasks (which are
*sync* — Celery's task body is not async) can drive them via
``asyncio.run``.

Why ``asyncio.run`` per call rather than one long-lived loop:

* The runner is *itself* async, and :meth:`BacktestJobRunner.run_once`
  is invoked via ``asyncio.run`` inside ``_run_job_sync``. That call
  already opens and closes its own loop. The pool and the cancel
  listener need to outlive that loop, so we open them before the
  runner's ``asyncio.run`` and close them after.
* The pool and the listener are process-local. Each Celery child
  worker gets its own; we open them lazily on the first task.
* All ``init`` helpers are idempotent (no-op if already open), so
  the second call in the same process is cheap.
"""

from __future__ import annotations

import asyncio
import logging
import sys

# Round #1204 (Tier 1): same psycopg3 / ProactorEventLoop guard as
# ``tasks.py`` — the lifespan helpers also call ``asyncio.run(...)``
# which defaults to Proactor on Windows. Setting the policy once at
# import is enough; ``asyncio.run`` reads it on each invocation.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from getrich.libs.postgres import pg_pool


logger = logging.getLogger(__name__)


def init_pg_pool() -> None:
    """Open the async PG pool for the current worker process.

    Idempotent. Logs and re-raises on failure so Celery marks the task
    as FAILED and the operator sees a clear error in the worker log.
    """
    try:
        asyncio.run(pg_pool.init())
    except Exception:
        logger.exception("pg_pool.init() failed in worker process")
        raise


def close_pg_pool() -> None:
    """Close the async PG pool, if open. Swallows errors at teardown."""
    try:
        asyncio.run(pg_pool.close())
    # silent-fail-ok: teardown is best-effort — the process is
    # exiting and the OS reclaims the socket. A failure here is
    # logged for ops visibility but cannot be raised (no caller
    # to handle it).
    except Exception:  # noqa: BLE001
        logger.exception("pg_pool.close() failed during worker teardown")


def init_cancel_listener() -> None:
    """Open the worker's cancel LISTEN connection (Round #1080).

    Idempotent: a second call without a matching ``close`` is a
    no-op. Failure is logged and swallowed — the runner's probe
    will fall back to the per-trial DB read on every call, which
    is correct but slower. The operator sees a single WARNING in
    the worker log, and the next reconnect attempt (driven by the
    pump's exponential backoff) will pick up automatically if PG
    recovers.
    """
    from getrich.apps.worker.cancel_listener import get_cancel_listener

    listener = get_cancel_listener()
    try:
        asyncio.run(listener.start())
    # silent-fail-ok: a failed LISTEN start is recoverable via the
    # DB probe fallback (see ``BacktestJobRunner._make_is_cancelled_fn``).
    # Logging the failure is enough — there is no caller to raise
    # to (this is called from a sync Celery task body).
    except Exception:  # noqa: BLE001
        logger.exception(
            "WorkerCancelListener.start() failed in worker process; "
            "runner will fall back to per-trial DB read",
        )


def close_cancel_listener() -> None:
    """Close the worker's cancel LISTEN connection, if open.

    Idempotent. Best-effort: errors are logged but never raised —
    teardown cannot fail in a way that has a caller to handle.
    """
    from getrich.apps.worker.cancel_listener import get_cancel_listener

    listener = get_cancel_listener()
    try:
        asyncio.run(listener.stop())
    # silent-fail-ok: see ``close_pg_pool`` — teardown is best-effort.
    except Exception:  # noqa: BLE001
        logger.exception("WorkerCancelListener.stop() failed during worker teardown")
