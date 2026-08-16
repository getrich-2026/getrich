"""Worker-side cross-process cancel probe driven by ``LISTEN`` (Round #1080).

Background
----------
Each backtest/sweep/walk-forward worker runs a long-lived
``BacktestJobRunner.run_once`` loop. The runner's per-trial
``is_cancelled`` probe used to be a short-lived sync ``psycopg``
``SELECT status FROM backtest_jobs`` per call (see
:func:`gr_api.jobs.persistence.sync_is_cancelled_status`).
That is correct but expensive — the probe fires on every trial /
bar / chunk — and has a race window: if the API process commits a
``status='cancelled'`` between two probes, the runner will only
notice on the *next* probe.

This module provides a *push-based* probe:

1. The worker process opens one long-lived PostgreSQL connection
   and runs ``LISTEN backtest_job_changed`` (the same channel the
   web side already notifies from inside the cancel
   transaction — see ``_NOTIFY_JOB_SQL`` in
   ``gr_api.jobs.persistence``).
2. A pump task loops over ``notifies()`` and adds the payload
   (a ``job_id``) to a process-local :class:`set` guarded by a
   :class:`threading.Lock`.
3. The runner's per-trial probe reads from the in-memory set.
   Latency: ~0 (the worker wakes up the moment the API's
   transaction commits the cancel + ``pg_notify``).

Failure mode is the same as the web-side
:class:`gr_api.services.job_listener.BacktestJobListener`:

* Connection drop → reconnect with exponential backoff (1 s → 30 s
  cap, ±20% jitter).
* Permanent PG outage → set stays empty; the runner falls back to
  the DB-read probe (``sync_is_cancelled_status``) on each
  trial, which costs ~1 ms but never lies.

Why both the listener and the DB probe?
-------------------------------------
The listener can miss a notify (PG restart, listener not yet
started when the cancel was committed, conn dropped mid-NOTIFY).
The DB read is the **safety net**: a single row read against a
primary key index is cheap, and the runner only does it when the
in-memory set doesn't have the job_id (which is the common case).
We don't replace the DB read with the listener — we *augment* it.

Threading model
---------------
The pump task is async and lives on the runner's event loop. The
probe is sync and may be called from any thread (the sync engine
inside an async op, a thread-pool executor, or a pytest
worker). The shared :class:`set` is therefore guarded by a
:class:`threading.Lock` so reads from the probe and writes from
the pump are race-free.
"""

from __future__ import annotations

import asyncio
import logging
import random
import threading
from contextlib import suppress
from typing import TYPE_CHECKING

import psycopg
from gr_data.config.settings import make_pg_dsn, settings


if TYPE_CHECKING:
    from psycopg import AsyncConnection


logger = logging.getLogger(__name__)


# Channel name. MUST match the literal in
# ``gr_api.jobs.persistence._NOTIFY_JOB_SQL`` so the
# listener sees the same notifications the SSE generator sees.
CHANNEL = "backtest_job_changed"

# Reconnect backoff bounds (seconds). Doubles on each consecutive
# failure, capped at ``_RECONNECT_MAX_S`` to keep recovery snappy
# even after a long PG outage. The first reconnect is immediate
# (after the initial backoff sleep).
_RECONNECT_MIN_S = 1.0
_RECONNECT_MAX_S = 30.0
_RECONNECT_JITTER_PCT = 0.2  # ±20%


class WorkerCancelListener:
    """Process-local cancel set driven by ``LISTEN backtest_job_changed``.

    A single PostgreSQL connection serves the whole worker process.
    The pump task reads ``notifies()`` and adds each payload to a
    process-local :class:`set` keyed on ``job_id``. The runner's
    per-trial probe calls :meth:`is_cancelled` to consult the set
    in O(1) without touching the DB.

    Lifecycle:

    * :meth:`start` opens a conn, runs ``LISTEN``, and spawns the
      pump task. Idempotent on re-entry (a second ``start`` is a
      no-op if the listener is already up).
    * :meth:`stop` cancels the pump, closes the conn, and clears
      the set. Idempotent on re-entry (a second ``stop`` is a
      no-op if the listener is already down).
    * :meth:`is_cancelled` is safe to call before ``start`` (returns
      ``False``) and after ``stop`` (also ``False``). It never
      raises.

    Failure mode is best-effort: any exception in ``start`` is
    logged and swallowed. The runner's probe will then fall back to
    the DB read for every trial (still correct, just slower).
    """

    def __init__(self) -> None:
        # The dedicated long-lived conn. Acquired in ``start()``
        # and in ``_pump`` after a reconnect. Closed in ``stop()``
        # and best-effort in ``_drop_conn``. The listener owns
        # this conn for the lifetime of the process — it is never
        # returned to the pool.
        self._conn: AsyncConnection | None = None
        self._task: asyncio.Task[None] | None = None
        # ``set[job_id]``. The cancel probe reads from this under
        # a lock; the pump writes to it under the same lock. We
        # use a plain ``set`` (not a dict) because we only need
        # presence checks.
        self._cancelled: set[str] = set()
        # The lock is shared between the pump task (async) and the
        # probe (sync, possibly called from a different thread).
        # ``threading.Lock`` is the right primitive for that.
        self._lock = threading.Lock()
        # ``_running`` flips to True after a successful ``start()``
        # and back to False after ``stop()``. The probe reads it
        # without holding the lock (a ``bool`` read is atomic in
        # CPython) to short-circuit the common case of "the worker
        # never enabled the listener" without paying for the lock.
        self._running: bool = False

    # ------------------------------------------------------------------ start / stop

    async def start(self) -> None:
        """Acquire a conn, run ``LISTEN``, spawn the pump task.

        Idempotent: a second ``start()`` while the listener is
        already running is a no-op. Any failure is logged and
        swallowed — the runner will fall back to the DB probe for
        every trial.
        """
        if self._running:
            return
        try:
            await self._reconnect()
        except Exception:
            logger.warning(
                "WorkerCancelListener: failed to acquire LISTEN connection; "
                "cancel probe will fall back to per-trial DB read",
                exc_info=True,
            )
            await self._drop_conn()
            return

        self._task = asyncio.create_task(self._pump(), name="worker_cancel_listener")
        self._running = True
        logger.info("WorkerCancelListener: listening on %s", CHANNEL)

    async def stop(self) -> None:
        """Cancel the pump task, close the conn, clear the set.

        Idempotent. Pending ``is_cancelled`` calls in flight when
        ``stop()`` is invoked will return ``False`` after this
        method returns — the runner can still rely on the DB
        fallback probe for any in-flight trial.
        """
        if not self._running and self._task is None and self._conn is None:
            return
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        await self._drop_conn()
        with self._lock:
            self._cancelled.clear()

    # ------------------------------------------------------------------ public probe

    def is_cancelled(self, job_id: str) -> bool:
        """Return ``True`` if a NOTIFY for *job_id* has been seen.

        Sync and thread-safe. Never raises. If the listener hasn't
        been started (or has been stopped), this returns ``False``
        — the runner treats that as "unknown, ask the DB" and the
        ``_make_is_cancelled_fn`` falls back to
        :func:`sync_is_cancelled_status`.

        Parameters
        ----------
        job_id : str
            The ``backtest_jobs.job_id`` to probe.

        Returns
        -------
        bool
            ``True`` iff the pump has observed a NOTIFY for
            *job_id* on the ``backtest_job_changed`` channel.
        """
        # Fast path: short-circuit on the bool without taking the
        # lock. The runner's hot path is "is this job still
        # running?" answered "no" ~99.9% of trials, so we want the
        # absolute-cheapest possible read.
        if not self._running:
            return False
        with self._lock:
            return job_id in self._cancelled

    # Test / introspection helpers (not part of the public contract
    # but useful in the test suite).
    def _unsafe_clear(self) -> None:
        """Clear the in-memory set. Test-only — production code
        must not call this.
        """
        with self._lock:
            self._cancelled.clear()

    def _unsafe_mark(self, job_id: str) -> None:
        """Add *job_id* to the in-memory set without going through
        the pump. Test-only — production code must not call this.
        """
        with self._lock:
            self._cancelled.add(job_id)

    # ------------------------------------------------------------------ pump

    async def _pump(self) -> None:
        """Long-lived task: pump ``notifies()`` into the cancelled set.

        On any exception other than ``CancelledError`` the task
        drops the dead conn, sleeps for a jittered exponential
        backoff (1 s → 30 s cap), and re-runs the connect + LISTEN
        sequence. The set is preserved across reconnects, so the
        runner's probe is correct as long as the listener was up
        *before* the cancel was committed.

        ``stop()`` cancels the task; the cancel is observed either
        inside the ``notifies()`` async-for (psycopg honours the
        event loop) or inside the backoff ``asyncio.sleep`` (which
        raises ``CancelledError`` immediately).
        """
        backoff = _RECONNECT_MIN_S
        while True:
            try:
                if self._conn is None:
                    # First iteration: ``start()`` set the conn
                    # already. Subsequent iterations: a previous
                    # ``notifies()`` raised and ``_drop_conn``
                    # cleared the slot.
                    await self._reconnect()
                assert self._conn is not None
                async for notify in self._conn.notifies():
                    # Reset backoff on any successful yield — a
                    # healthy stream keeps backoff at the floor.
                    backoff = _RECONNECT_MIN_S
                    with self._lock:
                        self._cancelled.add(notify.payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "WorkerCancelListener: notify pump died; reconnecting in %.1fs",
                    backoff,
                    exc_info=True,
                )
                await self._drop_conn()
                await self._sleep_jittered(backoff)
                backoff = min(backoff * 2, _RECONNECT_MAX_S)

    async def _reconnect(self) -> None:
        """Acquire a fresh conn and ``LISTEN`` on the channel.

        Raises on failure; the caller (``_pump``) catches and
        backs off. ``start()`` also catches and degrades to
        "no listener" — the runner's probe then returns ``False``
        and the DB-read fallback takes over.
        """
        dsn = make_pg_dsn(settings.postgres)
        # ``autocommit=True`` so LISTEN takes effect immediately
        # (LISTEN is a transaction-control command and only fires
        # at COMMIT) and notifications arrive on every commit by
        # the notifying process.
        self._conn = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
        async with self._conn.cursor() as cur:
            await cur.execute(f"LISTEN {CHANNEL}")

    async def _drop_conn(self) -> None:
        """Best-effort close of the dead conn so the socket is freed.

        Idempotent: a ``None`` conn or a conn that already raised
        on close is silently ignored — the goal is "make sure the
        slot is clear for the next reconnect attempt".
        """
        if self._conn is not None:
            with suppress(Exception):
                await self._conn.close()
            self._conn = None

    async def _sleep_jittered(self, seconds: float) -> None:
        """Sleep ``seconds`` ± ``_RECONNECT_JITTER_PCT``; cancel-aware.

        ``asyncio.sleep`` is the only place a backoff is observed,
        so cancelling the pump task during this sleep aborts the
        reconnect attempt promptly. ``stop()`` relies on this to
        tear down the listener in <100 ms even mid-reconnect.
        """
        low = seconds * (1.0 - _RECONNECT_JITTER_PCT)
        high = seconds * (1.0 + _RECONNECT_JITTER_PCT)
        # ``random.uniform`` is process-local and non-async; it is
        # safe to call here.
        await asyncio.sleep(random.uniform(low, high))


# ------------------------------------------------------------------ module singleton


# One listener per worker process. The runner's probe consults
# this directly via :func:`get_cancel_listener`. The lifespan
# helpers (:func:`init_cancel_listener` / :func:`close_cancel_listener`)
# own the lifecycle.
_LISTENER: WorkerCancelListener | None = None
_LISTENER_LOCK = threading.Lock()


def get_cancel_listener() -> WorkerCancelListener:
    """Return the process-local :class:`WorkerCancelListener`.

    Lazy-creates the listener on first access. The listener is
    *not* started by this call — :func:`init_cancel_listener`
    owns the start. The probe is safe to call on an un-started
    listener (returns ``False``).
    """
    global _LISTENER
    if _LISTENER is None:
        with _LISTENER_LOCK:
            if _LISTENER is None:
                _LISTENER = WorkerCancelListener()
    return _LISTENER


__all__ = [
    "CHANNEL",
    "WorkerCancelListener",
    "get_cancel_listener",
]
