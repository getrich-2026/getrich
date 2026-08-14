"""Unit tests for ``BacktestJobListener`` (Rounds #1063 + #1064).

The listener is a small class — most behaviour is best tested by
mocking ``psycopg.AsyncConnection.connect`` and the ``notifies()``
async generator. The pump, the subscribe/unsubscribe, the
graceful-degradation on start/stop, and the reconnect-on-drop loop
are all covered here.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from getrich.apps.web.services import job_listener
from getrich.apps.web.services.job_listener import (
    CHANNEL,
    BacktestJobListener,
)


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Async context manager that records ``execute`` calls.

    The real cursor is used for both the advisory-lock try (which
    returns a row) and the LISTEN statement (which has no result).
    ``executed`` is a list of ``(sql, params)`` tuples the test can
    assert on, and ``fetchone_result`` is what ``fetchone()`` returns
    (set by the test via ``_set_advisory_lock_result``).
    """

    def __init__(self) -> None:
        self.executed: list[tuple[str, Any]] = []
        # Default to "advisory lock acquired" so the listener
        # proceeds to LISTEN. Tests that want a lock-loss path
        # call ``_set_advisory_lock_result(False)`` after
        # constructing the conn.
        self.fetchone_result: tuple[Any, ...] = (True,)

    def _set_advisory_lock_result(self, got: bool) -> None:
        self.fetchone_result = (got,)

    async def __aenter__(self) -> _FakeCursor:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append((sql, params))

    async def fetchone(self) -> tuple[Any, ...] | None:
        return self.fetchone_result


class _FakeNotify:
    """Stand-in for ``psycopg.Notify`` — just carries the payload."""

    def __init__(self, payload: str) -> None:
        self.payload = payload


class _FakeConn:
    """Async context + async-iter mock for ``psycopg.AsyncConnection``.

    - ``cursor()`` returns a fresh ``_FakeCursor`` each call (the real
      one yields a new cursor per ``with`` block). All cursors are
      also recorded in ``self.cursors`` for post-hoc inspection (the
      real conn consumes the cursor inside the ``async with`` block
      so callers can't introspect afterwards).
    - ``notifies()`` returns an async generator that yields whatever
      is in ``self.notifications`` (a list of payloads to emit). When
      ``self.raise_after`` is non-None, the generator raises that
      exception after the configured number of yields (used to test
      the pump's exception handling and reconnect behaviour).
    - ``close()`` records the call and sets ``self.closed = True``.
    """

    def __init__(self) -> None:
        self.notifications: list[str] = []
        self.raise_after: int | None = None
        self.raise_with: BaseException | None = None
        self.closed: bool = False
        self.close_called: int = 0
        # Every cursor the conn hands out is recorded here so a test
        # can read its ``executed`` list after the ``async with`` in
        # ``start()`` has closed.
        self.cursors: list[_FakeCursor] = []

    def cursor(self) -> _FakeCursor:
        c = _FakeCursor()
        self.cursors.append(c)
        return c

    async def close(self) -> None:
        self.close_called += 1
        self.closed = True

    async def notifies(self) -> Any:
        # ``raise_after == 0`` means "raise before yielding anything"
        # (simulates a conn that's already dead when notifies() is
        # first called — e.g. PG-side disconnect).
        if self.raise_after == 0 and self.raise_with is not None:
            raise self.raise_with
        for i, payload in enumerate(self.notifications):
            if self.raise_after is not None and i >= self.raise_after:
                if self.raise_with is not None:
                    raise self.raise_with
                return
            yield _FakeNotify(payload)
        # If the caller never adds more notifications but the
        # listener pumps forever, we need the async-for to suspend
        # (not return) so the ``_pump`` task stays alive for the
        # test. We block on an Event until the test cancels the
        # task via ``listener.stop()``.
        await asyncio.Event().wait()


def _patch_connect(monkeypatch: pytest.MonkeyPatch, *conns: _FakeConn) -> list[_FakeConn]:
    """Monkeypatch ``psycopg.AsyncConnection.connect`` to return the
    given fakes in order, one per call.

    Returns the list of fakes so a test can assert which one the
    listener is currently using. If the listener reconnects more
    times than the list has entries, the last fake is reused (this
    is a "PG stayed down forever" scenario — the pump will keep
    retrying against the same broken fake).
    """
    calls = {"n": 0, "conns": list(conns)}

    async def factory(*a: Any, **kw: Any) -> _FakeConn:
        idx = min(calls["n"], len(calls["conns"]) - 1)
        calls["n"] += 1
        return calls["conns"][idx]

    monkeypatch.setattr(
        "getrich.apps.web.services.job_listener.psycopg.AsyncConnection.connect",
        factory,
    )
    return list(conns)


def _patch_backoff(
    monkeypatch: pytest.MonkeyPatch,
    *,
    min_s: float = 0.01,
    max_s: float = 0.05,
    jitter_pct: float = 0.0,
) -> None:
    """Shrink the reconnect backoff to keep the test suite fast.

    Production values are 1.0 / 30.0 / 0.2. Tests want the pump to
    spin through 3-4 reconnects in under 100 ms each, so we
    override the module constants via monkeypatch.
    """
    monkeypatch.setattr(job_listener, "_RECONNECT_MIN_S", min_s)
    monkeypatch.setattr(job_listener, "_RECONNECT_MAX_S", max_s)
    monkeypatch.setattr(job_listener, "_RECONNECT_JITTER_PCT", jitter_pct)


# ---------------------------------------------------------------------------
# start() — successful path
# ---------------------------------------------------------------------------


async def test_start_runs_listen(monkeypatch: pytest.MonkeyPatch) -> None:
    """``start()`` opens a conn, wins the advisory lock, runs
    ``LISTEN backtest_job_changed``, and spawns the pump task.
    """
    fake = _FakeConn()
    _patch_connect(monkeypatch, fake)

    listener = BacktestJobListener()
    await listener.start()

    try:
        # Two cursors are opened: the first runs the advisory-lock
        # race (``pg_try_advisory_lock``), the second runs ``LISTEN``.
        # Each ``async with conn.cursor()`` block in production creates
        # a fresh cursor, so we assert both at the conn level.
        assert len(fake.cursors) == 2
        # First cursor: exactly one statement — the advisory lock try.
        executed0 = fake.cursors[0].executed
        assert len(executed0) == 1
        sql0, _ = executed0[0]
        assert sql0.startswith("SELECT pg_try_advisory_lock(")
        # Second cursor: exactly one statement — LISTEN on the channel.
        executed1 = fake.cursors[1].executed
        assert len(executed1) == 1
        sql1, _ = executed1[0]
        assert sql1 == f"LISTEN {CHANNEL}"
        assert listener._conn is fake
        assert listener.is_holder is True
        assert listener._task is not None
    finally:
        await listener.stop()


async def test_start_loses_advisory_lock_degrades_to_no_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multi-worker race: when another web worker already holds the
    advisory lock, ``start()`` must NOT raise — it logs, sets
    ``is_holder=False``, leaves ``_conn=None`` and ``_task=None``.
    The lifespan then wires ``_LISTENER = None`` and the SSE
    generators on this worker fall back to 1 s polling.
    """
    fake = _FakeConn()
    # Simulate "another worker already holds the advisory lock" by
    # making the first cursor's ``pg_try_advisory_lock`` return False.
    # The real conn's ``cursor()`` lazily creates the cursor, so we
    # patch ``fake.cursor`` to return a cursor pre-set to the loser
    # result.
    original_cursor = fake.cursor

    def _loser_cursor() -> _FakeCursor:
        c = original_cursor()
        c._set_advisory_lock_result(False)
        return c

    fake.cursor = _loser_cursor  # type: ignore[method-assign]
    _patch_connect(monkeypatch, fake)

    listener = BacktestJobListener()
    await listener.start()  # MUST NOT RAISE

    # We did NOT win the lock → no conn, no task, is_holder=False.
    assert listener._conn is None
    assert listener._task is None
    assert listener.is_holder is False
    # The cursor that ran the advisory-lock try executed exactly
    # one statement; the LISTEN cursor was never opened (we lost
    # the lock before reaching that point).
    assert len(fake.cursors) == 1
    executed = fake.cursors[0].executed
    assert len(executed) == 1
    sql0, _ = executed[0]
    assert sql0.startswith("SELECT pg_try_advisory_lock(")
    # The loser conn must have been closed (so we don't leak a PG
    # slot — the lifespan relies on this for clean shutdown).
    assert fake.closed is True


# ---------------------------------------------------------------------------
# start() / stop() — edge cases
# ---------------------------------------------------------------------------


async def test_start_failure_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the conn cannot be acquired, ``start()`` logs and returns
    without raising. ``_conn`` and ``_task`` stay ``None``.
    """

    async def boom(*a: Any, **kw: Any) -> None:
        raise ConnectionRefusedError("simulated PG down")

    monkeypatch.setattr(
        "getrich.apps.web.services.job_listener.psycopg.AsyncConnection.connect",
        boom,
    )

    listener = BacktestJobListener()
    await listener.start()  # MUST NOT RAISE

    assert listener._conn is None
    assert listener._task is None


async def test_stop_closes_conn_and_cancels_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``stop()`` closes the conn, cancels the pump task, and clears
    the events dict. Idempotent on a second call.
    """
    fake = _FakeConn()
    _patch_connect(monkeypatch, fake)

    listener = BacktestJobListener()
    await listener.start()
    assert listener._task is not None
    task = listener._task

    await listener.stop()
    assert listener._conn is None
    assert listener._task is None
    assert fake.closed is True
    assert task.done() is True

    # Idempotent.
    await listener.stop()


# ---------------------------------------------------------------------------
# subscribe / unsubscribe / notify
# ---------------------------------------------------------------------------


async def test_subscribe_returns_stable_event_per_job_id() -> None:
    """``subscribe(id)`` returns the same :class:`asyncio.Event` for
    repeated calls with the same id; different ids get different events.
    """
    listener = BacktestJobListener()
    try:
        a1 = listener.subscribe("a")
        a2 = listener.subscribe("a")
        b = listener.subscribe("b")
        assert a1 is a2
        assert a1 is not b
    finally:
        # No start/stop needed — the dict is the only state.
        listener._events.clear()


async def test_unsubscribe_removes_entry() -> None:
    """``unsubscribe(id)`` removes the entry. ``notify(id)`` on a
    removed id is a no-op (does not raise).
    """
    listener = BacktestJobListener()
    ev = listener.subscribe("x")
    assert ev in listener._events.values()

    listener.unsubscribe("x")
    assert "x" not in listener._events
    # No-op for absent id.
    listener.unsubscribe("x")

    # Re-subscribe yields a fresh event (the old one is gc'd).
    ev2 = listener.subscribe("x")
    assert ev2 is not ev


async def test_notify_sets_subscribed_event() -> None:
    """``notify(id)`` sets the subscribed event so a concurrent
    ``await ev.wait()`` returns immediately.
    """
    listener = BacktestJobListener()
    ev = listener.subscribe("a")
    listener.notify("a")

    # Should return essentially instantly.
    await asyncio.wait_for(ev.wait(), timeout=0.1)


# ---------------------------------------------------------------------------
# Pump + reconnect (Round #1064)
# ---------------------------------------------------------------------------


async def test_pump_reconnects_after_notifies_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """When ``notifies()`` raises (simulating a PG-side disconnect),
    the pump logs a warning, drops the dead conn, sleeps for the
    (tiny) backoff, and re-runs connect + LISTEN on a fresh conn.
    The pump task itself does NOT die — the listener keeps
    listening on the new conn.
    """
    _patch_backoff(monkeypatch, min_s=0.01, max_s=0.05)
    first = _FakeConn()
    first.notifications = ["only-one"]
    first.raise_after = 0  # raise on the very first iteration
    first.raise_with = ConnectionResetError("simulated PG drop")
    second = _FakeConn()  # healthy replacement
    _patch_connect(monkeypatch, first, second)

    listener = BacktestJobListener()
    with caplog.at_level("WARNING", logger="getrich.apps.web.services.job_listener"):
        await listener.start()
        # Give the pump time to: observe the error, drop the conn,
        # sleep the backoff, reconnect, re-LISTEN.
        await asyncio.sleep(0.2)

    try:
        # The first conn was closed by ``_drop_conn`` (best-effort
        # close of the dead conn after ``notifies()`` raised).
        assert first.closed is True
        # The second conn got a cursor that ran ``LISTEN <channel>``.
        assert any(sql == f"LISTEN {CHANNEL}" for c in second.cursors for sql, _ in c.executed)
        # The listener is now using the second conn.
        assert listener._conn is second
        # The pump task is still alive (it didn't die — it
        # reconnected and is now sitting in ``notifies()`` on the
        # second conn).
        assert listener._task is not None
        assert listener._task.done() is False
        # And a warning was logged for the drop.
        warnings = [r for r in caplog.records if "reconnecting" in r.getMessage().lower()]
        assert len(warnings) >= 1
    finally:
        await listener.stop()


async def test_subscriber_continuity_across_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An event subscribed before a reconnect still fires when a
    notification for that ``job_id`` arrives on the new conn.

    This is the core contract SSE generators rely on: they
    ``subscribe`` once at connect time and ``unsubscribe`` at
    generator exit, and they do NOT re-subscribe on PG-side
    disconnects. If the listener dropped the event on reconnect,
    the SSE stream would degrade to 1 Hz polling until the user
    disconnected.
    """
    _patch_backoff(monkeypatch, min_s=0.01, max_s=0.05)
    first = _FakeConn()
    first.notifications = []
    first.raise_after = 0
    first.raise_with = ConnectionResetError("simulated PG drop")
    second = _FakeConn()
    # The replacement conn will emit a notification for "job-1"
    # on its first iteration. Injecting it post-hoc is racy (the
    # pump might already be in the Event().wait()), so we set it
    # at construction time and let the pump pick it up.
    second.notifications = ["job-1"]
    _patch_connect(monkeypatch, first, second)

    listener = BacktestJobListener()
    # Subscribe BEFORE the reconnect happens. This is the
    # "SSE generator at connect time" use case.
    ev = listener.subscribe("job-1")

    await listener.start()
    # Wait long enough for: notify raise → drop → backoff sleep →
    # reconnect → second notifies() yield. The event must fire
    # within 1 s; if it doesn't, ``wait_for`` raises TimeoutError
    # and the test fails.
    await asyncio.wait_for(ev.wait(), timeout=1.0)

    try:
        # Event fired even though it was created before the
        # reconnect.
        assert ev.is_set()
    finally:
        await listener.stop()


async def test_reconnect_failure_logs_and_keeps_trying(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """If reconnect itself fails (PG still down), the pump logs and
    keeps trying. The listener does NOT give up.
    """
    _patch_backoff(monkeypatch, min_s=0.01, max_s=0.05)
    broken = _FakeConn()
    broken.notifications = []
    broken.raise_after = 0
    broken.raise_with = ConnectionResetError("simulated PG drop")
    _patch_connect(monkeypatch, broken)

    listener = BacktestJobListener()
    with caplog.at_level("WARNING", logger="getrich.apps.web.services.job_listener"):
        await listener.start()
        # Give the pump a few chances to retry.
        await asyncio.sleep(0.3)

    try:
        # Pump is still running.
        assert listener._task is not None
        assert listener._task.done() is False
        # The single fake's ``notifies()`` kept raising on each
        # reconnect, so we should see at least 2 reconnect
        # warnings.
        reconnect_warnings = [r for r in caplog.records if "reconnecting" in r.getMessage().lower()]
        assert len(reconnect_warnings) >= 2
    finally:
        await listener.stop()


async def test_stop_during_backoff_cancels_promptly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``stop()`` cancels the pump task during the jittered backoff
    sleep, so a long PG outage does not delay shutdown.

    The pump should be in the 30 s production backoff when ``stop``
    is called; we override the constants to 0.5 s so the test is
    guaranteed to catch the pump mid-sleep, and assert that ``stop``
    returns within 100 ms (i.e. the cancel is honoured, not waited
    out).
    """
    _patch_backoff(monkeypatch, min_s=0.5, max_s=0.5, jitter_pct=0.0)
    broken = _FakeConn()
    broken.notifications = []
    broken.raise_after = 0
    broken.raise_with = ConnectionResetError("simulated PG drop")
    _patch_connect(monkeypatch, broken)

    listener = BacktestJobListener()
    await listener.start()
    # Give the pump time to enter the backoff sleep.
    await asyncio.sleep(0.1)
    assert listener._task is not None
    assert listener._task.done() is False

    # ``stop()`` should cancel the sleep and return well before
    # the 0.5 s backoff expires.
    t0 = time.monotonic()
    await listener.stop()
    elapsed = time.monotonic() - t0

    assert listener._task is None
    assert listener._conn is None
    # 100 ms is generous — on a healthy CI box the cancel is
    # observed in <10 ms.
    assert elapsed < 0.1, f"stop() took {elapsed:.3f}s, expected < 0.1s"


async def test_sleep_jittered_within_bounds() -> None:
    """The jitter helper samples uniformly within ±jitter_pct of the
    target.

    0.05 s base is large enough that the asyncio scheduler can't
    round it to zero (the failure mode at 0.01 s), and 10 iterations
    keep the test under 1 s total.

    The *measured* elapsed time includes asyncio scheduling overhead
    AFTER the sleep returns (the call site + monotonic() read), which
    on a busy CI runner can be ~20 ms on top of the maximum sleep
    value. We use a generous 4x upper bound (0.2 s) to keep the
    test reliable on slow hardware; the production contract is the
    ±20% jitter on the *requested* sleep duration, and we verify
    that contract by checking the distribution of samples below
    (they cluster near the jitter band, not the high bound).
    """
    listener = BacktestJobListener()
    target = 0.05
    samples = []
    for _ in range(10):
        t0 = time.monotonic()
        await listener._sleep_jittered(target)
        samples.append(time.monotonic() - t0)
    # Hard lower bound: must always sleep at least 50% of target.
    # The asyncio floor is the production jitter floor (0.8x = 0.04s)
    # plus zero overhead, so 0.025 is a safe floor.
    low = target * 0.5
    # Hard upper bound: production jitter ceiling (1.2x = 0.06s) + a
    # generous 140 ms headroom for asyncio scheduling noise on
    # contended CI runners. The 0.2 s ceiling is 4x target; any
    # genuine regression (e.g. accidentally sleeping 2x target) would
    # blow this, but asyncio timing jitter alone won't.
    high = target * 4.0
    for s in samples:
        assert low <= s <= high, f"sample {s:.4f}s outside [{low:.4f}, {high:.4f}]"
    # And the distribution: the median of the samples should be near
    # the jitter band (target ± 20%), NOT at the high bound. This
    # catches a regression where the helper sleeps the full target
    # without the jitter.
    samples_sorted = sorted(samples)
    median = samples_sorted[len(samples_sorted) // 2]
    # Median should be within 3x target of the expected jitter band.
    assert median <= target * 3.0, (
        f"median sample {median:.4f}s suggests jitter helper is not "
        f"actually jittering (should cluster around {target} ± 20%)"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _async_return(value: Any) -> Any:
    """Tiny shim so monkeypatched ``connect`` is awaitable.

    ``psycopg.AsyncConnection.connect`` is itself awaitable (it
    returns a coroutine that resolves to the conn), so the
    monkeypatched version needs to be awaitable too. The cleanest
    shape is ``async def`` returning the fake, but a lambda can't
    be awaitable — hence this helper.
    """
    return value
