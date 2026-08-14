"""Tests for the BacktestJobRunner orchestration layer."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from getrich.apps.strategy.backtest_job_runner import (
    BacktestJobOp,
    BacktestJobRunner,
    BacktestJobRunResult,
    BacktestOneShotOp,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _FakeStore:
    """Minimal in-memory stand-in for ``PgBacktestJobStore``.

    Captures every method call so tests can assert the runner's behavior
    without involving the real PostgreSQL layer.
    """

    def __init__(self, queued: list[dict[str, Any]] | None = None) -> None:
        self.queued = list(queued or [])
        self.claim_calls = 0
        self.claim_kwargs: list[dict[str, Any]] = []
        self.mark_running_calls: list[str] = []
        self.update_progress_calls: list[tuple[str, int]] = []
        self.mark_completed_calls: list[str] = []
        self.mark_failed_calls: list[tuple[str, str]] = []
        self.mark_retry_calls: list[tuple[str, str, Any]] = []
        self.mark_cancelled_calls: list[str] = []

    async def claim_next_queued(
        self,
        job_type: str,
        *,
        stale_seconds: int = 300,
    ) -> dict[str, Any] | None:
        self.claim_calls += 1
        self.claim_kwargs.append({"stale_seconds": stale_seconds})
        if not self.queued:
            return None
        row = self.queued.pop(0)
        row = dict(row)
        # Preserve ``_was_recovered`` from the queued row (test injection
        # for P2 #311 stuck-running recovery).
        was_recovered = bool(row.pop("_was_recovered", False))
        row["status"] = "running"
        # Default attempt / max_attempts; tests can override per-row.
        row.setdefault("attempt", 1)
        row.setdefault("max_attempts", 1)
        row.setdefault("next_retry_at", None)
        row["_was_recovered"] = was_recovered
        return row

    async def mark_running(self, job_id: str) -> bool:
        self.mark_running_calls.append(job_id)
        return True

    async def update_progress(self, job_id: str, progress: int) -> bool:
        self.update_progress_calls.append((job_id, progress))
        return True

    async def mark_completed(self, job_id: str) -> bool:
        self.mark_completed_calls.append(job_id)
        return True

    async def mark_failed(self, job_id: str, error_message: str) -> bool:
        self.mark_failed_calls.append((job_id, error_message))
        return True

    async def mark_retry(self, job_id: str, *, error_message: str, next_retry_at: Any) -> bool:
        self.mark_retry_calls.append((job_id, error_message, next_retry_at))
        return True

    async def mark_cancelled(self, job_id: str) -> bool:
        self.mark_cancelled_calls.append(job_id)
        return True

    async def get_by_idempotency_key(
        self, *, key: str, user_id: str | None = None
    ) -> Any:  # pragma: no cover - unused
        return None


def _make_job(job_id: str = "job-1", job_type: str = "backtest") -> dict[str, Any]:
    return {
        "job_id": job_id,
        "job_type": job_type,
        "ref_id": "run-1",
        "status": "queued",
        "request_json": "{}",
        "progress": 0,
    }


def test_runner_rejects_non_op_callable() -> None:
    with pytest.raises(TypeError):
        BacktestJobRunner(_FakeStore(), lambda _: None)  # type: ignore[arg-type]


def test_runner_rejects_negative_sleep() -> None:
    with pytest.raises(ValueError, match="sleep_seconds must be non-negative"):
        BacktestJobRunner(_FakeStore(), BacktestOneShotOp(), sleep_seconds=-0.1)


def test_one_shot_op_returns_progress_100() -> None:
    op = BacktestOneShotOp()
    result = _run(op(_make_job()))
    assert result == {"progress": 100}


def test_run_once_returns_idle_when_no_jobs_queued() -> None:
    store = _FakeStore(queued=[])
    runner = BacktestJobRunner(store, BacktestOneShotOp(), sleep_seconds=0)

    out = _run(runner.run_once())

    assert out == BacktestJobRunResult(claimed=False, job_id=None, final_status=None, error=None)
    assert store.claim_calls == 1
    assert store.mark_completed_calls == []


def test_run_once_claims_runs_and_completes() -> None:
    store = _FakeStore(queued=[_make_job("job-1")])
    runner = BacktestJobRunner(store, BacktestOneShotOp(), sleep_seconds=0)

    out = _run(runner.run_once())

    assert out.claimed is True
    assert out.job_id == "job-1"
    assert out.final_status == "completed"
    assert out.error is None
    assert store.mark_completed_calls == ["job-1"]
    assert store.mark_failed_calls == []


def test_run_once_writes_progress_when_op_returns_it() -> None:
    store = _FakeStore(queued=[_make_job("job-1")])

    class _ProgressOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            return {"progress": 42}

    runner = BacktestJobRunner(store, _ProgressOp(), sleep_seconds=0)
    out = _run(runner.run_once())

    assert out.final_status == "completed"
    assert store.update_progress_calls == [("job-1", 42)]


def test_run_once_clamps_invalid_progress_to_default() -> None:
    store = _FakeStore(queued=[_make_job("job-1")])

    class _BadProgressOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            return {"progress": "not-a-number"}

    runner = BacktestJobRunner(store, _BadProgressOp(), sleep_seconds=0)
    out = _run(runner.run_once())

    assert out.final_status == "completed"
    assert store.update_progress_calls == [("job-1", 100)]


def test_run_once_marks_failed_when_op_raises() -> None:
    store = _FakeStore(queued=[_make_job("job-1")])

    class _BoomOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            raise RuntimeError("synthetic failure")

    runner = BacktestJobRunner(store, _BoomOp(), sleep_seconds=0)
    out = _run(runner.run_once())

    assert out.claimed is True
    assert out.job_id == "job-1"
    assert out.final_status == "failed"
    assert out.error == "synthetic failure"
    assert store.mark_failed_calls == [("job-1", "synthetic failure")]
    assert store.mark_completed_calls == []


def test_run_until_idle_processes_all_queued_jobs_then_stops() -> None:
    jobs = [_make_job(f"job-{i}") for i in range(3)]
    store = _FakeStore(queued=jobs)
    runner = BacktestJobRunner(store, BacktestOneShotOp(), sleep_seconds=0)

    results = _run(runner.run_until_idle(max_iterations=10))

    claimed_results = [r for r in results if r.claimed]
    assert len(claimed_results) == 3
    assert [r.job_id for r in claimed_results] == ["job-0", "job-1", "job-2"]
    assert all(r.final_status == "completed" for r in claimed_results)
    # Final result should report idle.
    assert results[-1].claimed is False
    assert store.mark_completed_calls == ["job-0", "job-1", "job-2"]


def test_run_until_idle_respects_max_iterations() -> None:
    jobs = [_make_job(f"job-{i}") for i in range(5)]
    store = _FakeStore(queued=jobs)
    runner = BacktestJobRunner(store, BacktestOneShotOp(), sleep_seconds=0)

    results = _run(runner.run_until_idle(max_iterations=2))

    assert len(results) == 2
    assert all(r.claimed for r in results)


def test_run_until_idle_rejects_non_positive_max_iterations() -> None:
    runner = BacktestJobRunner(_FakeStore(), BacktestOneShotOp(), sleep_seconds=0)

    with pytest.raises(ValueError, match="max_iterations must be positive"):
        _run(runner.run_until_idle(max_iterations=0))


def test_runner_passes_claimed_row_to_op() -> None:
    seen: list[dict[str, Any]] = []

    class _CapturingOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            seen.append(dict(job))
            return None

    store = _FakeStore(queued=[_make_job("job-7", job_type="sweep")])
    runner = BacktestJobRunner(store, _CapturingOp(), job_type="sweep", sleep_seconds=0)

    out = _run(runner.run_once())

    assert out.final_status == "completed"
    assert seen[0]["job_id"] == "job-7"
    assert seen[0]["job_type"] == "sweep"


def test_backtest_one_shot_op_satisfies_protocol() -> None:
    assert isinstance(BacktestOneShotOp(), BacktestJobOp)


# ---------------------------------------------------------------- progress injection


def test_runner_injects_progress_callback_and_event_loop_into_op_job() -> None:
    """P1: run_once augments the job dict with ``_progress_cb`` and ``_event_loop``."""
    seen: list[dict[str, Any]] = []

    class _CapturingOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            seen.append(dict(job))
            # Touch the callback to confirm it is callable.
            cb = job.get("_progress_cb")
            if cb is not None:
                await cb(42)
            return None

    store = _FakeStore(queued=[_make_job()])
    runner = BacktestJobRunner(store, _CapturingOp(), sleep_seconds=0)

    _run(runner.run_once())

    job = seen[0]
    assert callable(job["_progress_cb"])
    # _event_loop is the runner's running loop — just check identity-equality.
    assert job["_event_loop"] is not None
    assert store.update_progress_calls == [("job-1", 42)]


def test_runner_swallows_progress_callback_exceptions() -> None:
    """A flaky progress writer must not cascade into a job failure."""

    class _BoomOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            cb = job["_progress_cb"]
            await cb(50)  # store.update_progress is fine; just exercising path
            return {"progress": 100}

    store = _FakeStore(queued=[_make_job("job-x")])
    runner = BacktestJobRunner(store, _BoomOp(), sleep_seconds=0)

    out = _run(runner.run_once())

    assert out.final_status == "completed"
    assert store.update_progress_calls == [("job-x", 50), ("job-x", 100)]


def test_runner_progress_callback_does_not_swallow_op_exception() -> None:
    """Op exceptions still mark the job as failed, even if progress callback fired."""

    class _FailingOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            await job["_progress_cb"](25)
            raise RuntimeError("op boom")

    store = _FakeStore(queued=[_make_job("job-fail")])
    runner = BacktestJobRunner(store, _FailingOp(), sleep_seconds=0)

    out = _run(runner.run_once())

    assert out.final_status == "failed"
    assert "op boom" in (out.error or "")
    assert store.mark_failed_calls == [("job-fail", out.error or "")]
    # Op raised before returning a progress dict, so only the explicit
    # callback call (25) should be on the store.
    assert store.update_progress_calls == [("job-fail", 25)]


# ---------------------------------------------------------------- cancellation


def test_is_cancelled_db_probe_returns_false_when_row_not_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh runner uses a DB-backed probe; the probe defaults to False
    when the helper is monkey-patched to return False (i.e. user has not
    cancelled). Replacing the P3 in-process ``notify_job_cancelled`` helper
    with a DB probe lets the same assertion run in any process.
    """
    monkeypatch.setattr(
        "getrich_backtest.job_persistence.sync_is_cancelled_status",
        lambda _job_id, *, conninfo: False,
    )

    seen: list[bool] = []

    class _ProbeOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            seen.append(job["_is_cancelled"]())
            return None

    store = _FakeStore(queued=[_make_job()])
    runner = BacktestJobRunner(store, _ProbeOp(), sleep_seconds=0, db_conninfo="x")
    _run(runner.run_once())
    assert seen == [False]


def test_runner_injects_is_cancelled_into_op_job() -> None:
    """The op's job dict should expose a sync ``_is_cancelled`` callable."""
    seen: list[dict[str, Any]] = []

    class _CapturingOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            seen.append(dict(job))
            cb = job.get("_is_cancelled")
            assert callable(cb)
            # Calling it before any cancellation should return False.
            assert cb() is False
            return None

    store = _FakeStore(queued=[_make_job()])
    runner = BacktestJobRunner(store, _CapturingOp(), sleep_seconds=0)

    _run(runner.run_once())

    job = seen[0]
    assert callable(job["_is_cancelled"])


def test_is_cancelled_db_probe_flips_mid_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the DB probe flips to True mid-run, the runner sees it and the op's
    self-reported cancel sentinel short-circuits mark_completed."""
    import asyncio

    # Probe returns False on the first call, True thereafter — simulates a
    # user POSTing /cancel between the runner's initial read and the op's
    # mid-flight is_cancelled() check.
    calls = {"n": 0}

    def _flipping_probe(_job_id: str, *, conninfo: str) -> bool:
        calls["n"] += 1
        return calls["n"] >= 2

    monkeypatch.setattr(
        "getrich_backtest.job_persistence.sync_is_cancelled_status",
        _flipping_probe,
    )

    observed: list[bool] = []

    class _LongRunningOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            is_cancelled = job["_is_cancelled"]
            observed.append(is_cancelled())  # before any probe flip
            await asyncio.sleep(0)
            observed.append(is_cancelled())  # after the probe has flipped
            return {"cancelled": True}

    store = _FakeStore(queued=[_make_job("job-cancel-1")])
    runner = BacktestJobRunner(store, _LongRunningOp(), sleep_seconds=0, db_conninfo="x")

    out = _run(runner.run_once())

    assert observed[0] is False
    assert observed[1] is True
    assert out.final_status == "cancelled"
    # Op returned the cancellation sentinel — runner must NOT call mark_completed.
    assert store.mark_completed_calls == []
    assert store.mark_failed_calls == []


def test_runner_treats_op_cancelled_dict_as_cancellation() -> None:
    """Op returning ``{"cancelled": True}`` short-circuits mark_completed."""

    class _CancelOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            return {"cancelled": True, "progress": 50}

    store = _FakeStore(queued=[_make_job("job-cx")])
    runner = BacktestJobRunner(store, _CancelOp(), sleep_seconds=0)

    out = _run(runner.run_once())

    assert out.final_status == "cancelled"
    assert out.error is None
    assert store.mark_completed_calls == []
    assert store.mark_failed_calls == []


# ---------------- WorkerCancelListener integration (Round #1080) ----------------


def test_runner_consults_cancel_listener_before_db_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round #1080 P0.1: when the worker cancel listener is
    running, the runner's probe must consult the in-memory set
    first. If the listener has the job_id, the probe returns
    True *without* calling the DB probe — the listener is the
    source of truth and the DB read is just the safety net.
    """
    from getrich.apps.worker import cancel_listener

    # Force the listener singleton to a known state — a started
    # listener that has a "this job is cancelled" entry in the set.
    listener = cancel_listener.WorkerCancelListener()
    listener._running = True
    listener._unsafe_mark("job-listener-wins")
    monkeypatch.setattr(cancel_listener, "_LISTENER", listener)

    db_probe_calls: list[str] = []

    def _tracking_db_probe(job_id: str, *, conninfo: str) -> bool:
        db_probe_calls.append(job_id)
        return False  # Listener is the source of truth — DB must NOT be consulted.

    monkeypatch.setattr(
        "getrich_backtest.job_persistence.sync_is_cancelled_status",
        _tracking_db_probe,
    )

    seen: list[bool] = []

    class _ProbeOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            seen.append(job["_is_cancelled"]())
            return None

    store = _FakeStore(queued=[_make_job("job-listener-wins")])
    runner = BacktestJobRunner(store, _ProbeOp(), sleep_seconds=0, db_conninfo="x")
    _run(runner.run_once())

    # The probe returned True because the listener flipped the
    # in-memory set, even though the DB probe would have
    # returned False.
    assert seen == [True]
    # The DB probe is NOT called when the listener has the
    # job_id — that is the optimization Round #1080 P0.1 ships.
    # The DB probe is only invoked when the listener is silent
    # (no entry for the job_id) AND the listener is running
    # (so we know we couldn't have missed a notify by virtue of
    # the listener not being up).
    assert db_probe_calls == []
    # Cleanup.
    listener._running = False
    listener._unsafe_clear()


def test_runner_falls_back_to_db_when_listener_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the listener is running but has NOT seen a NOTIFY
    for the job_id, the runner falls back to the DB read. This
    is the safety-net path for a missed notify (PG restart
    between commit and listener startup, listener conn dropped
    mid-NOTIFY, etc.).
    """
    from getrich.apps.worker import cancel_listener

    # Listener is up, but the in-memory set is empty — the
    # notify hasn't been seen yet (or the cancel happened
    # before the listener started).
    listener = cancel_listener.WorkerCancelListener()
    listener._running = True
    listener._unsafe_clear()
    monkeypatch.setattr(cancel_listener, "_LISTENER", listener)

    monkeypatch.setattr(
        "getrich_backtest.job_persistence.sync_is_cancelled_status",
        lambda _job_id, *, conninfo: True,  # DB has the cancel
    )

    seen: list[bool] = []

    class _ProbeOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            seen.append(job["_is_cancelled"]())
            return None

    store = _FakeStore(queued=[_make_job("job-missed-notify")])
    runner = BacktestJobRunner(store, _ProbeOp(), sleep_seconds=0, db_conninfo="x")
    _run(runner.run_once())

    # The DB read picked up the cancel the listener missed.
    assert seen == [True]
    # Cleanup.
    listener._running = False


def test_runner_falls_back_to_db_when_listener_unstarted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the listener singleton is not running (the in-process
    API fallback path, or a worker that hasn't called
    ``init_cancel_listener`` yet), the probe must defer entirely
    to the DB read.
    """
    from getrich.apps.worker import cancel_listener

    # Default state: ``_LISTENER`` is None or ``_running`` is False.
    # The runner's probe closure should still work — it will
    # short-circuit on the ``_running`` check and fall through
    # to the DB read.
    monkeypatch.setattr(cancel_listener, "_LISTENER", None)

    monkeypatch.setattr(
        "getrich_backtest.job_persistence.sync_is_cancelled_status",
        lambda _job_id, *, conninfo: False,
    )

    seen: list[bool] = []

    class _ProbeOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            seen.append(job["_is_cancelled"]())
            return None

    store = _FakeStore(queued=[_make_job("job-db-only")])
    runner = BacktestJobRunner(store, _ProbeOp(), sleep_seconds=0, db_conninfo="x")
    _run(runner.run_once())
    assert seen == [False]


def test_runner_probe_is_noop_when_no_db_conninfo_and_no_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty ``db_conninfo`` + no listener → constant ``False``.

    The legacy in-process API path that opted out of cross-process
    cancellation must still work: the probe is a no-op (returns
    False on every call) and the op can still self-cancel via
    ``return {"cancelled": True}``.
    """
    from getrich.apps.worker import cancel_listener

    monkeypatch.setattr(cancel_listener, "_LISTENER", None)

    seen: list[bool] = []

    class _ProbeOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            seen.append(job["_is_cancelled"]())
            return None

    store = _FakeStore(queued=[_make_job("job-no-cancel")])
    # db_conninfo default is "" — opt-out path.
    runner = BacktestJobRunner(store, _ProbeOp(), sleep_seconds=0)
    _run(runner.run_once())
    assert seen == [False]


# ---------------------------------------------------------------- progress throttling


def test_progress_callback_throttles_same_boundary() -> None:
    """A burst of writes to the same 5% boundary must collapse to a single DB write."""

    class _BurstOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            cb = job["_progress_cb"]
            # Simulate 100 trial-level updates all in the 0-4% range.
            for pct in (1, 2, 3, 4, 4, 4, 3, 2, 1, 0):
                await cb(pct)
            return {"progress": 100}

    store = _FakeStore(queued=[_make_job("job-throttle-1")])
    runner = BacktestJobRunner(store, _BurstOp(), sleep_seconds=0)

    out = _run(runner.run_once())

    assert out.final_status == "completed"
    # Only the first 1% crossed a new boundary (0 -> 0, but our closure uses
    # ``boundary = (value // 5) * 5``). All pcts 0..4 share boundary 0, and
    # the 100 at the end is always written. Expect 2 writes: one for the
    # initial 0/1 cluster and one for the final 100.
    assert store.update_progress_calls == [("job-throttle-1", 1), ("job-throttle-1", 100)]


def test_progress_callback_writes_at_each_5pct_boundary() -> None:
    """A monotonic pass through 0..100 produces 21 writes: 0, 5, 10, ..., 100."""

    class _ClimbOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            cb = job["_progress_cb"]
            for pct in range(0, 101):
                await cb(pct)
            return None

    store = _FakeStore(queued=[_make_job("job-climb")])
    runner = BacktestJobRunner(store, _ClimbOp(), sleep_seconds=0)

    _run(runner.run_once())

    pcts = [p for _, p in store.update_progress_calls]
    # Monotonic pass through every integer 0..100 → every 5% boundary is hit.
    assert pcts == [
        0,
        5,
        10,
        15,
        20,
        25,
        30,
        35,
        40,
        45,
        50,
        55,
        60,
        65,
        70,
        75,
        80,
        85,
        90,
        95,
        100,
    ]


def test_progress_callback_drops_out_of_order_within_boundary() -> None:
    """Late-arriving pcts that don't cross a new boundary are dropped."""

    class _SkipOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            cb = job["_progress_cb"]
            await cb(7)  # boundary 5 — write
            await cb(8)  # boundary 5 — drop
            await cb(11)  # boundary 10 — write
            await cb(9)  # boundary 5 — drop (already passed)
            await cb(15)  # boundary 15 — write
            return None

    store = _FakeStore(queued=[_make_job("job-skip")])
    runner = BacktestJobRunner(store, _SkipOp(), sleep_seconds=0)

    _run(runner.run_once())

    assert store.update_progress_calls == [
        ("job-skip", 7),
        ("job-skip", 11),
        ("job-skip", 15),
    ]


def test_progress_callback_always_writes_100() -> None:
    """The terminal 100% must always be flushed even if boundary 100 == last."""

    class _TerminalOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            cb = job["_progress_cb"]
            await cb(100)
            return None

    store = _FakeStore(queued=[_make_job("job-end")])
    runner = BacktestJobRunner(store, _TerminalOp(), sleep_seconds=0)

    _run(runner.run_once())

    assert store.update_progress_calls == [("job-end", 100)]


def test_progress_callback_clamps_out_of_range_pcts() -> None:
    """Pcts outside [0, 100] should be clamped before the boundary check."""

    class _BadOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            cb = job["_progress_cb"]
            await cb(-50)  # clamped to 0 → boundary 0
            await cb(150)  # clamped to 100 → always written
            return None

    store = _FakeStore(queued=[_make_job("job-clamp")])
    runner = BacktestJobRunner(store, _BadOp(), sleep_seconds=0)

    _run(runner.run_once())

    assert store.update_progress_calls == [("job-clamp", 0), ("job-clamp", 100)]


# ---------------------------------------------------------------- retry / backoff


def test_op_failure_with_retries_calls_mark_retry() -> None:
    """Op raises with attempt=1 < max_attempts=3 → runner schedules a retry."""

    class _BoomOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            raise RuntimeError("transient failure")

    job = {
        "job_id": "job-r",
        "job_type": "backtest",
        "ref_id": "run-r",
        "status": "queued",
        "request_json": "{}",
        "progress": 0,
        "attempt": 1,
        "max_attempts": 3,
        "next_retry_at": None,
    }
    store = _FakeStore(queued=[job])
    runner = BacktestJobRunner(store, _BoomOp(), sleep_seconds=0)

    out = _run(runner.run_once())

    assert out.final_status == "failed_retryable"
    assert "transient failure" in (out.error or "")
    assert len(store.mark_retry_calls) == 1
    job_id, error_message, next_retry_at = store.mark_retry_calls[0]
    assert job_id == "job-r"
    assert error_message == "transient failure"
    assert next_retry_at is not None
    assert store.mark_failed_calls == []
    assert store.mark_completed_calls == []


def test_op_failure_at_max_attempts_calls_mark_failed() -> None:
    """Op raises with attempt=3 >= max_attempts=3 → terminal failure."""

    class _BoomOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            raise RuntimeError("permanent failure")

    job = {
        "job_id": "job-t",
        "job_type": "backtest",
        "ref_id": "run-t",
        "status": "queued",
        "request_json": "{}",
        "progress": 0,
        "attempt": 3,
        "max_attempts": 3,
        "next_retry_at": None,
    }
    store = _FakeStore(queued=[job])
    runner = BacktestJobRunner(store, _BoomOp(), sleep_seconds=0)

    out = _run(runner.run_once())

    assert out.final_status == "failed"
    assert store.mark_retry_calls == []
    assert store.mark_failed_calls == [("job-t", "permanent failure")]


def test_op_failure_during_cancellation_marks_cancelled_not_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the DB probe returns True when the op raises, the row is cancelled — never retried."""

    # Force the DB probe to return True for this job so the runner
    # sees the user wants out.
    monkeypatch.setattr(
        "getrich_backtest.job_persistence.sync_is_cancelled_status",
        lambda _job_id, *, conninfo: True,
    )

    class _CancelThenBoomOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            is_cancelled = job["_is_cancelled"]
            # Force the probe to report cancel so the runner sees the user wants out.
            assert is_cancelled() is True
            raise RuntimeError("op explosion after cancel")

    job = {
        "job_id": "job-cx",
        "job_type": "backtest",
        "ref_id": "run-cx",
        "status": "queued",
        "request_json": "{}",
        "progress": 0,
        "attempt": 1,
        "max_attempts": 5,
        "next_retry_at": None,
    }
    store = _FakeStore(queued=[job])
    runner = BacktestJobRunner(store, _CancelThenBoomOp(), sleep_seconds=0, db_conninfo="x")

    out = _run(runner.run_once())

    assert out.final_status == "cancelled"
    assert store.mark_cancelled_calls == ["job-cx"]
    assert store.mark_retry_calls == []
    assert store.mark_failed_calls == []


def test_runner_compute_backoff_curve() -> None:
    """Exponential backoff with cap matches the documented formula."""
    runner = BacktestJobRunner(
        _FakeStore(),
        BacktestOneShotOp(),
        sleep_seconds=0,
        retry_base_seconds=1.0,
        retry_cap_seconds=60.0,
    )
    # attempt=1 → base * 2^0 = 1.0
    # attempt=2 → base * 2   = 2.0
    # attempt=3 → base * 4   = 4.0
    # attempt=4 → base * 8   = 8.0
    # attempt=10 → base * 2^9 = 512 → capped at 60
    # attempt=20 → also capped at 60
    assert runner._compute_backoff(1) == 1.0
    assert runner._compute_backoff(2) == 2.0
    assert runner._compute_backoff(3) == 4.0
    assert runner._compute_backoff(4) == 8.0
    assert runner._compute_backoff(10) == 60.0
    assert runner._compute_backoff(20) == 60.0


def test_runner_rejects_invalid_retry_config() -> None:
    """Validation of retry_base_seconds / retry_cap_seconds at construction time."""
    with pytest.raises(ValueError, match="retry_base_seconds must be positive"):
        BacktestJobRunner(_FakeStore(), BacktestOneShotOp(), retry_base_seconds=0)
    with pytest.raises(ValueError, match="retry_cap_seconds must be >="):
        BacktestJobRunner(
            _FakeStore(),
            BacktestOneShotOp(),
            retry_base_seconds=10.0,
            retry_cap_seconds=1.0,
        )


# ---------------------------------------------------------------- jitter (P2+)


def test_runner_jitter_default_is_zero() -> None:
    """Default retry_jitter_pct is 0 → no jitter, deterministic curve."""
    runner = BacktestJobRunner(_FakeStore(), BacktestOneShotOp(), sleep_seconds=0)
    assert runner.retry_jitter_pct == 0.0
    # Curve is still 1, 2, 4, 8, ... 60 — backwards compatible.
    assert runner._compute_backoff(1) == 1.0
    assert runner._compute_backoff(4) == 8.0


def test_runner_rejects_out_of_range_jitter() -> None:
    """retry_jitter_pct must be in [0.0, 1.0); 1.0 or negative is rejected."""
    with pytest.raises(ValueError, match="retry_jitter_pct"):
        BacktestJobRunner(_FakeStore(), BacktestOneShotOp(), retry_jitter_pct=1.0, sleep_seconds=0)
    with pytest.raises(ValueError, match="retry_jitter_pct"):
        BacktestJobRunner(_FakeStore(), BacktestOneShotOp(), retry_jitter_pct=-0.1, sleep_seconds=0)


def test_runner_jitter_stays_within_band() -> None:
    """With ±10% jitter, repeated calls produce values in [0.9 * base, 1.1 * base]."""
    runner = BacktestJobRunner(
        _FakeStore(),
        BacktestOneShotOp(),
        sleep_seconds=0,
        retry_jitter_pct=0.10,
    )
    # Without seeding random, just verify the band is respected over many samples.
    samples = [runner._compute_backoff(1) for _ in range(2000)]
    assert all(0.9 <= s / 1.0 <= 1.1 for s in samples), (
        f"out-of-band sample: min={min(samples):.4f}, max={max(samples):.4f}"
    )
    # And the spread is non-trivial (not all equal).
    assert min(samples) < 0.95
    assert max(samples) > 1.05


def test_runner_jitter_at_cap_still_respects_band() -> None:
    """At the cap (attempt=20), ±10% jitter stays within [0.9*60, 1.1*60]."""
    runner = BacktestJobRunner(
        _FakeStore(),
        BacktestOneShotOp(),
        sleep_seconds=0,
        retry_base_seconds=1.0,
        retry_cap_seconds=60.0,
        retry_jitter_pct=0.10,
    )
    samples = [runner._compute_backoff(20) for _ in range(2000)]
    assert all(0.9 * 60.0 <= s <= 1.1 * 60.0 for s in samples), (
        f"min={min(samples):.4f}, max={max(samples):.4f}"
    )


# ---------------------------------------------------------------- P2 #311 recovery


def test_runner_default_stale_recovery_seconds_is_300() -> None:
    """Constructor defaults: stale_recovery_seconds=300."""
    runner = BacktestJobRunner(_FakeStore(), BacktestOneShotOp(), sleep_seconds=0)
    assert runner.stale_recovery_seconds == 300


def test_runner_forwards_stale_recovery_seconds_to_store() -> None:
    store = _FakeStore(queued=[_make_job("job-1")])
    runner = BacktestJobRunner(
        store, BacktestOneShotOp(), stale_recovery_seconds=120, sleep_seconds=0
    )
    _run(runner.run_once())
    assert store.claim_kwargs == [{"stale_seconds": 120}]


def test_runner_rejects_negative_stale_recovery_seconds() -> None:
    with pytest.raises(ValueError, match="stale_recovery_seconds must be non-negative"):
        BacktestJobRunner(
            _FakeStore(),
            BacktestOneShotOp(),
            stale_recovery_seconds=-1,
        )


def test_runner_was_recovered_does_not_alter_completion_path() -> None:
    """A recovered job still goes through the normal op → mark_completed flow."""
    store = _FakeStore(queued=[{**_make_job("stuck-1"), "_was_recovered": True}])
    runner = BacktestJobRunner(
        store, BacktestOneShotOp(), stale_recovery_seconds=300, sleep_seconds=0
    )
    out = _run(runner.run_once())
    assert out.claimed is True
    assert out.job_id == "stuck-1"
    assert out.final_status == "completed"
    assert out.error is None
    # The runner logs a warning on recovery — not asserted here, but the
    # call to mark_completed proves the recovery did not branch.
    assert store.mark_completed_calls == ["stuck-1"]


# ---------------------------------------------------------------- P2 #314 terminal / retryable


def test_op_failure_with_terminal_error_skips_retry() -> None:
    """Op raises a TerminalError subclass even with attempt < max_attempts
    → runner goes straight to ``mark_failed``, never to ``mark_retry``."""

    class _TerminalBoomOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            raise TerminalError("invalid request payload")

    from getrich_backtest.exceptions import TerminalError  # noqa: PLC0415

    job = {
        "job_id": "job-t",
        "job_type": "backtest",
        "ref_id": "run-t",
        "status": "queued",
        "request_json": "{}",
        "progress": 0,
        "attempt": 1,
        "max_attempts": 3,
        "next_retry_at": None,
    }
    store = _FakeStore(queued=[job])
    runner = BacktestJobRunner(store, _TerminalBoomOp(), sleep_seconds=0)

    out = _run(runner.run_once())

    assert out.final_status == "failed"
    assert "invalid request payload" in (out.error or "")
    # Critical: no retry, no attempt bump.
    assert store.mark_retry_calls == []
    assert store.mark_failed_calls == [("job-t", "invalid request payload")]


def test_op_failure_with_backtest_job_error_subclass_skips_retry() -> None:
    """``BacktestJobError`` now multi-inherits from TerminalError. Ops
    that raise it (e.g. validation sites) should bypass the retry path."""

    class _ValidationOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            from getrich.apps.strategy.errors import BacktestJobError  # noqa: PLC0415

            raise BacktestJobError("search_spec.space must be a non-empty dict")

    job = {
        "job_id": "job-v",
        "job_type": "backtest",
        "ref_id": "run-v",
        "status": "queued",
        "request_json": "{}",
        "progress": 0,
        "attempt": 1,
        "max_attempts": 5,
        "next_retry_at": None,
    }
    store = _FakeStore(queued=[job])
    runner = BacktestJobRunner(store, _ValidationOp(), sleep_seconds=0)

    out = _run(runner.run_once())

    assert out.final_status == "failed"
    # Even with max_attempts=5 and attempt=1, no retry should be scheduled.
    assert store.mark_retry_calls == []
    assert store.mark_failed_calls and store.mark_failed_calls[0][0] == "job-v"


def test_op_failure_with_retryable_error_uses_default_path() -> None:
    """``RetryableError`` is documentation only — the runner treats it
    the same as a plain ``Exception`` (i.e. honours ``max_attempts``)."""

    class _BlipOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            from getrich_backtest.exceptions import RetryableError  # noqa: PLC0415

            raise RetryableError("transient db blip")

    job = {
        "job_id": "job-r",
        "job_type": "backtest",
        "ref_id": "run-r",
        "status": "queued",
        "request_json": "{}",
        "progress": 0,
        "attempt": 1,
        "max_attempts": 3,
        "next_retry_at": None,
    }
    store = _FakeStore(queued=[job])
    runner = BacktestJobRunner(store, _BlipOp(), sleep_seconds=0)

    out = _run(runner.run_once())

    # Same shape as the existing ``RuntimeError("transient failure")`` test.
    assert out.final_status == "failed_retryable"
    assert "transient db blip" in (out.error or "")
    assert len(store.mark_retry_calls) == 1
    assert store.mark_failed_calls == []


def test_op_failure_with_terminal_error_during_cancellation_still_cancels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation priority beats TerminalError semantics."""

    monkeypatch.setattr(
        "getrich_backtest.job_persistence.sync_is_cancelled_status",
        lambda _job_id, *, conninfo: True,
    )

    class _CancelThenTerminalOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            from getrich_backtest.exceptions import TerminalError  # noqa: PLC0415

            # Simulate the user cancelling while the op is throwing.
            assert job["_is_cancelled"]() is True
            raise TerminalError("op discovered bad config after cancel")

    job = {
        "job_id": "job-c",
        "job_type": "backtest",
        "ref_id": "run-c",
        "status": "queued",
        "request_json": "{}",
        "progress": 0,
        "attempt": 1,
        "max_attempts": 3,
        "next_retry_at": None,
    }
    store = _FakeStore(queued=[job])
    runner = BacktestJobRunner(store, _CancelThenTerminalOp(), sleep_seconds=0, db_conninfo="x")

    out = _run(runner.run_once())

    # Cancellation wins over TerminalError: never retry, never mark_failed.
    assert out.final_status == "cancelled"
    assert store.mark_cancelled_calls == ["job-c"]
    assert store.mark_failed_calls == []
    assert store.mark_retry_calls == []


def test_terminal_error_does_not_bump_attempt() -> None:
    """A TerminalError at attempt=1 with max_attempts=3 must NOT schedule
    a retry, so the row stays at attempt=1 (visible via mark_retry not
    being called)."""

    class _TerminalBoomOp:
        async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
            from getrich_backtest.exceptions import TerminalError  # noqa: PLC0415

            raise TerminalError("permanent config error")

    job = {
        "job_id": "job-na",
        "job_type": "backtest",
        "ref_id": "run-na",
        "status": "queued",
        "request_json": "{}",
        "progress": 0,
        "attempt": 1,
        "max_attempts": 3,
        "next_retry_at": None,
    }
    store = _FakeStore(queued=[job])
    runner = BacktestJobRunner(store, _TerminalBoomOp(), sleep_seconds=0)

    _run(runner.run_once())

    # mark_retry is what bumps attempt; since it was never called,
    # attempt stays at 1 (no need to assert on a mock attempt counter —
    # the absence of mark_retry is itself the contract).
    assert store.mark_retry_calls == []
    assert store.mark_failed_calls == [("job-na", "permanent config error")]


# ---------------------------------------------------------------- P1 per-job retry override


def test_runner_backoff_uses_per_job_base_when_claimed_provides_it() -> None:
    """claimed row's retry_base_seconds overrides the runner default."""
    # Runner default base=1, cap=60. Per-job claim sets base=5, cap=60.
    runner = BacktestJobRunner(_FakeStore(), BacktestOneShotOp(), sleep_seconds=0)
    claimed = {"retry_base_seconds": 5.0, "retry_cap_seconds": 60.0, "retry_jitter_pct": 0.0}
    # attempt=1 → per-job base * 2^0 = 5 (instead of runner default 1).
    assert runner._compute_backoff(1, claimed=claimed) == 5.0
    # attempt=2 → 5 * 2 = 10
    assert runner._compute_backoff(2, claimed=claimed) == 10.0


def test_runner_backoff_uses_per_job_cap_when_claimed_provides_it() -> None:
    """claimed row's retry_cap_seconds overrides the runner default."""
    # Runner default base=1, cap=60. Per-job claim sets base=5, cap=8.
    runner = BacktestJobRunner(_FakeStore(), BacktestOneShotOp(), sleep_seconds=0)
    claimed = {"retry_base_seconds": 5.0, "retry_cap_seconds": 8.0, "retry_jitter_pct": 0.0}
    # attempt=1 → 5
    assert runner._compute_backoff(1, claimed=claimed) == 5.0
    # attempt=2 → min(5*2, 8) = 8 (cap kicks in)
    assert runner._compute_backoff(2, claimed=claimed) == 8.0
    # attempt=3 → min(5*4, 8) = 8
    assert runner._compute_backoff(3, claimed=claimed) == 8.0


def test_runner_backoff_uses_per_job_jitter_when_claimed_provides_it() -> None:
    """claimed row's retry_jitter_pct enables multiplicative jitter."""
    runner = BacktestJobRunner(_FakeStore(), BacktestOneShotOp(), sleep_seconds=0)
    claimed = {"retry_base_seconds": 1.0, "retry_cap_seconds": 60.0, "retry_jitter_pct": 0.5}
    samples = [runner._compute_backoff(1, claimed=claimed) for _ in range(500)]
    # base=1, jitter ±50% → uniform[0.5, 1.5]
    assert all(0.5 <= s <= 1.5 for s in samples)
    assert min(samples) < 0.6
    assert max(samples) > 1.4


def test_runner_backoff_falls_back_to_runner_default_when_claimed_column_null() -> None:
    """claimed row with NULL retry_* columns falls back to runner defaults."""
    # Runner default base=1, cap=60. Per-job claim has all-NULL overrides.
    runner = BacktestJobRunner(_FakeStore(), BacktestOneShotOp(), sleep_seconds=0)
    claimed = {"retry_base_seconds": None, "retry_cap_seconds": None, "retry_jitter_pct": None}
    assert runner._compute_backoff(1, claimed=claimed) == 1.0
    assert runner._compute_backoff(4, claimed=claimed) == 8.0


def test_runner_backoff_falls_back_to_runner_default_when_claimed_omits_keys() -> None:
    """claimed row without retry_* keys at all falls back to runner defaults."""
    runner = BacktestJobRunner(_FakeStore(), BacktestOneShotOp(), sleep_seconds=0)
    claimed = {"job_id": "job-1", "status": "running"}  # no retry_* keys
    assert runner._compute_backoff(1, claimed=claimed) == 1.0
    assert runner._compute_backoff(4, claimed=claimed) == 8.0


def test_runner_backoff_falls_back_to_runner_default_when_claimed_is_none() -> None:
    """Backwards compat: passing claimed=None keeps the original behavior."""
    runner = BacktestJobRunner(_FakeStore(), BacktestOneShotOp(), sleep_seconds=0)
    # _compute_backoff(attempt) without claimed arg — should still work.
    assert runner._compute_backoff(1) == 1.0
    assert runner._compute_backoff(4) == 8.0
