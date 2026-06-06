"""Worker process lifespan helpers.

A Celery worker runs ``task`` functions in *worker child processes*
(many, depending on ``--concurrency``). Each child process needs:

1. A live async ``pg_pool`` (the runner uses async psycopg for its
   lifecycle writes).
2. A clean teardown when the task finishes (or the worker dies).

This module exposes :func:`init_pg_pool` and :func:`close_pg_pool`,
small sync wrappers around the async :class:`PgConnectionPool` API,
so the Celery tasks (which are *sync* — Celery's task body is not
async) can drive the pool via ``asyncio.run``.

Why ``asyncio.run`` per call rather than one long-lived loop:

* The runner is *itself* async, and :meth:`BacktestJobRunner.run_once`
  is invoked via ``asyncio.run`` inside ``_run_job_sync``. That call
  already opens and closes its own loop. The pool needs to outlive
  that loop, so we open it before the runner's ``asyncio.run`` and
  close it after.
* The pool is process-local. Each Celery child worker gets its own
  pool; we open it lazily on the first task.
* ``init`` is idempotent (a no-op if the pool is already open), so
  the second call in the same process is cheap.
"""

from __future__ import annotations

import asyncio
import logging

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
