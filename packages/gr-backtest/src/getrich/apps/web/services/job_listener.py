"""Cross-process wakeup for backtest_job SSE streams.

The web process owns a single, long-lived PostgreSQL connection
that runs ``LISTEN backtest_job_changed``. The worker side appends
``SELECT pg_notify('backtest_job_changed', '<job_id>')`` to the same
transaction that mutates the row, so notifications fire only after
the new state is visible to other connections. Result: worker → SSE
latency drops from up to ``POLL_INTERVAL_S`` (1 s) to ~10 ms (the
PostgreSQL NOTIFY round-trip).

The 1 s polling safety net in each SSE generator is preserved — a
missed notification (listener not started, conn dropped mid-flight,
or a payload the listener did not have a subscriber for) costs at
most 1 s of UI latency, the same as before this round.

The listener auto-reconnects on connection drop (PG restart, network
glitch, etc.) with exponential backoff: 1 s → 30 s cap, ±20 % jitter
to avoid thundering-herd storms when several web processes all
disconnect together. The subscriber dict survives reconnects, so
SSE generators do not need to re-subscribe.

Failure mode is graceful: if the LISTEN connection cannot be acquired
or LISTEN itself fails, ``start()`` logs a warning and returns. The
SSE generators continue to poll. ``stop()`` cancels the pump task
(including any in-flight backoff sleep) and closes the connection;
any in-flight ``wait_for`` on a subscriber times out via the 1 s
safety net and falls through to a normal poll.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from contextlib import suppress
from typing import TYPE_CHECKING

import psycopg

from gr_data.config.settings import make_pg_dsn, settings


if TYPE_CHECKING:
    from psycopg import AsyncConnection


logger = logging.getLogger(__name__)


# Channel name. Matches the literal in
# ``getrich_backtest.job_persistence._NOTIFY_JOB_SQL``.
CHANNEL = "backtest_job_changed"

# Advisory-lock key for the cross-worker race. The value is a
# 64-bit signed int; we use a stable hash of the channel name so
# other apps using the same PG cluster don't accidentally collide
# (PG advisory locks are cluster-global). The hash uses the same
# algorithm as ``hashtext`` in PG (``pg_try_advisory_lock`` accepts
# a bigint; we compute it once in Python for symmetry).
_ADVISORY_KEY = int.from_bytes(
    hashlib.blake2b(CHANNEL.encode("utf-8"), digest_size=8).digest(),
    byteorder="big",
    signed=True,
)

# Raised by ``_reconnect`` when another web worker already holds
# the advisory lock. ``start()`` catches and degrades to no-listener
# (the SSE generators then fall back to 1 s polling).
class _NotListenerHolderError(Exception):
    """Internal: another web worker holds the listener advisory lock."""


# Reconnect backoff bounds (seconds). Doubles on each consecutive
# failure, capped at ``_RECONNECT_MAX_S`` to keep recovery snappy
# even after a long PG outage. The first reconnect is immediate
# (after the initial backoff sleep).
_RECONNECT_MIN_S = 1.0
_RECONNECT_MAX_S = 30.0
_RECONNECT_JITTER_PCT = 0.2  # ±20%


class BacktestJobListener:
    """Process-local pubsub of backtest_jobs NOTIFY events.

    A single PostgreSQL connection serves all subscribers: SSE
    generators ``subscribe(job_id)`` to receive an
    :class:`asyncio.Event` that fires whenever PostgreSQL notifies
    the channel with that job's id. Multiple SSE generators can
    subscribe to the same ``job_id`` safely — each gets its own
    :class:`asyncio.Event` keyed on the id.
    """

    def __init__(self) -> None:
        # The dedicated long-lived conn. Acquired in ``start()`` and
        # in ``_pump`` after a reconnect. Closed in ``stop()`` and
        # best-effort in ``_drop_conn``. We never use the pool's
        # ``connection()`` context manager (which auto-releases the
        # conn on exit and would break LISTEN), and we never call
        # ``putconn()`` on it — the listener owns this conn for the
        # lifetime of the process.
        self._conn: AsyncConnection | None = None
        self._task: asyncio.Task[None] | None = None
        # ``dict[job_id, asyncio.Event]``. Each subscriber gets its
        # own event so multiple SSE generators can subscribe to the
        # same job independently. Events are created lazily in
        # ``subscribe`` and removed in ``unsubscribe``. The dict
        # survives reconnects so SSE generators never need to
        # re-subscribe.
        self._events: dict[str, asyncio.Event] = {}

    async def start(self) -> None:
        """Acquire a conn, run ``LISTEN``, and spawn the pump task.

        Best-effort: any failure is logged and swallowed. The SSE
        generators always check ``_LISTENER`` before subscribing,
        so the listener may be started but non-functional without
        breaking the polling fallback.

        When ``_reconnect`` raises ``_NotListenerHolderError`` (another
        web worker is already the listener), this is *expected*
        and silent — we just log at info level. The non-holders
        have ``listener = None`` set by the lifespan so SSE falls
        back to polling.
        """
        try:
            await self._reconnect()
        except _NotListenerHolderError as e:
            logger.info(
                "BacktestJobListener: not the LISTEN holder (%s); "
                "SSE streams on this worker will fall back to polling",
                e,
            )
            self._holder = False
            return
        except Exception:
            logger.warning(
                "BacktestJobListener: failed to acquire LISTEN connection; "
                "SSE streams will fall back to polling",
                exc_info=True,
            )
            await self._drop_conn()
            self._holder = False
            return

        self._holder = True
        self._task = asyncio.create_task(self._pump(), name="backtest_job_listener")
        logger.info("BacktestJobListener: listening on %s", CHANNEL)

    @property
    def is_holder(self) -> bool:
        """True iff this worker won the advisory-lock race.

        The lifespan uses this to decide whether to install the
        listener into the SSE service modules (``_LISTENER``)
        or leave them as ``None`` (polling fallback).
        """
        return getattr(self, "_holder", False)

    async def stop(self) -> None:
        """Cancel the pump task, close the conn, drain subscribers.

        Any pending ``wait_for`` on a subscriber event will hit the
        1 s safety net and fall through to a normal poll — the
        intent is to let the SSE generator continue, not to abort
        the stream. The events dict is cleared so a subsequent
        ``start()`` starts from a clean slate.

        If we are the advisory-lock holder, release the lock
        explicitly before closing the conn (session-scoped locks
        die with the conn anyway, but being explicit helps when
        debugging via ``pg_locks``).
        """
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        if self._conn is not None:
            # Best-effort advisory unlock (idempotent — the lock
            # dies with the conn if we miss it).
            with suppress(Exception):
                async with self._conn.cursor() as cur:
                    await cur.execute(
                        "SELECT pg_advisory_unlock(%s)",
                        (_ADVISORY_KEY,),
                    )
            with suppress(Exception):
                await self._conn.close()
            self._conn = None
        # Wake any pending subscribers so the SSE generator's
        # ``wait_for`` doesn't have to wait the full timeout before
        # falling through to the poll. The events themselves are
        # sticky (asyncio.Event semantics) — the next ``wait()``
        # call would return immediately even after ``clear()`` is
        # called below, but the SSE generator always ``clear()``s
        # the event after waking, so draining the dict is the
        # correct cleanup.
        for ev in self._events.values():
            ev.set()
        self._events.clear()

    def subscribe(self, job_id: str) -> asyncio.Event:
        """Return (creating if needed) the event for *job_id*.

        Each call returns the same :class:`asyncio.Event` for a
        given id within the listener's lifetime, so an SSE
        generator that calls ``subscribe`` at connect time and
        ``unsubscribe`` at generator exit gets exactly one event
        to drive its ``wait_for`` loop.
        """
        ev = self._events.get(job_id)
        if ev is None:
            ev = asyncio.Event()
            self._events[job_id] = ev
        return ev

    def unsubscribe(self, job_id: str) -> None:
        """Remove the event for *job_id*. No-op if absent.

        Does NOT call ``ev.set()`` — the consumer's
        ``wait_for(timeout=POLL_INTERVAL_S)`` times out and falls
        through to a normal poll, preserving the heartbeat and
        poll cadence.
        """
        self._events.pop(job_id, None)

    def notify(self, job_id: str) -> None:
        """Test injection: synchronously set the event for *job_id*.

        The production pump task does not call this — it sets
        events from inside the ``notifies()`` async-for loop. Tests
        inject wakeups directly so the SSE generator's
        ``wait_for(ev.wait(), timeout=...)`` returns within
        milliseconds rather than seconds.
        """
        ev = self._events.get(job_id)
        if ev is not None:
            ev.set()

    async def _pump(self) -> None:
        """Long-lived task: pump ``notifies()`` into subscriber events.

        On any exception other than ``CancelledError`` the task
        drops the dead conn, sleeps for a jittered exponential
        backoff (1 s → 30 s cap), and re-runs the connect + LISTEN
        sequence. The subscriber dict is preserved across
        reconnects, so SSE generators do not need to re-subscribe.

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
                    # The notify's payload is the ``job_id`` we
                    # passed to ``pg_notify`` in the worker's
                    # transaction. Reset backoff on any successful
                    # yield — a healthy stream keeps backoff at the
                    # floor.
                    backoff = _RECONNECT_MIN_S
                    ev = self._events.get(notify.payload)
                    if ev is not None:
                        ev.set()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "BacktestJobListener: notify pump died; reconnecting in %.1fs",
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
        "no listener" — the SSE generators then poll.

        **Multi-worker guard**: when ``uvicorn --workers N`` runs,
        each worker calls ``start()``. We use
        ``pg_try_advisory_lock`` to elect exactly one worker as
        the LISTEN holder. Non-holders raise ``_NotListenerHolderError``
        (which ``start()`` swallows and degrades to polling). The
        lock is *session-scoped* — it lives as long as the conn,
        so the holder's ``stop()`` must explicitly release it
        (otherwise restarts leak it until the conn is reaped).
        """
        dsn = make_pg_dsn(settings.postgres)
        # ``autocommit=True`` so LISTEN takes effect immediately
        # (LISTEN is a transaction-control command and only fires
        # at COMMIT) and notifications arrive on every commit by
        # the notifying process.
        self._conn = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
        # Race for the advisory lock. If another worker already
        # holds it, close our conn (so we don't leak a PG slot)
        # and signal "not the holder".
        async with self._conn.cursor() as cur:
            await cur.execute(
                "SELECT pg_try_advisory_lock(%s) AS got",
                (_ADVISORY_KEY,),
            )
            row = await cur.fetchone()
            got = bool(row and row[0])
        if not got:
            await self._conn.close()
            self._conn = None
            raise _NotListenerHolderError(
                f"another web worker holds advisory lock {_ADVISORY_KEY}",
            )
        # We're the elected holder — run LISTEN.
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


__all__ = ["BacktestJobListener", "CHANNEL"]
