"""Tests for the GET /backtest-walk-forwards/{walk_forward_id}/events SSE endpoint.

The endpoint streams lifecycle events for one walk-forward study, keyed
on the *walk-forward* row (not the parent job):

* ``event: snapshot`` (first frame)
* zero or more ``event: update``
* ``event: done`` (when the parent job reaches a terminal status)
* close

The wire format mirrors :func:`backtest_sweep.stream_sweep_events` and
:func:`backtest_job.stream_job_events`. The ``data:`` payload is the
:func:`_walk_forward_detail` (walk-forward row + parent job merged
in) so the page can ``setQueryData`` the whole row in one shot.

Most tests in this file exercise the async generator
``walk_forward_svc.stream_walk_forward_events`` directly with a fake
``Request``. ASGITransport does not faithfully simulate client
disconnects, so a pure call-and-iterate approach is the most reliable
way to assert event sequencing. The router-level HTTP tests are kept
narrow (404 on cross-user, 401 on anonymous) since they don't rely on
the stream lifecycle.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from getrich.apps.web.deps import get_db, require_user
from getrich.apps.web.routers.backtest_walk_forwards import router
from getrich.apps.web.services import backtest_walk_forward as walk_forward_svc


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------- fixtures


class _FakeCursor:
    def __init__(
        self,
        *,
        fetchone: dict[str, Any] | None = None,
    ) -> None:
        self._fetchone = fetchone
        self.executed: list[tuple[str, dict[str, Any] | None]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, sql: str, params: dict[str, Any] | None = None) -> None:
        self.executed.append((sql, params))

    async def fetchone(self) -> dict[str, Any] | None:
        return self._fetchone


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _FakeCursor:
        return self._cursor


class _FakeRequest:
    """Minimal stand-in for fastapi.Request used by the SSE generator.

    Only ``is_disconnected()`` is needed. We flip a flag when the test
    consumer has finished reading so the generator can return early
    instead of waiting for ``_POLL_INTERVAL_S`` to expire.
    """

    def __init__(self) -> None:
        self._disconnected = False

    async def is_disconnected(self) -> bool:
        return self._disconnected

    def disconnect(self) -> None:
        self._disconnected = True


def _wf_row(
    *,
    walk_forward_id: str = "wf-1",
    user_id: str | None = "user-1",
    status: str = "running",
    total_windows: int = 4,
    completed_windows: int = 0,
    failed_windows: int = 0,
    updated_at: datetime | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Build a fake ``backtest_walk_forwards`` row matching the inline SQL."""
    row: dict[str, Any] = {
        "walk_forward_id": walk_forward_id,
        "user_id": user_id,
        "search_type": "expanding",
        "search_spec": {"p": [1, 2, 3]},
        "select_metric": "sharpe",
        "maximize": True,
        "refit": True,
        "status": status,
        "total_windows": total_windows,
        "completed_windows": completed_windows,
        "failed_windows": failed_windows,
        "mean_validation_metric": None,
        "summary_json": None,
        "created_at": datetime(2026, 6, 4, 9, 30),
        "completed_at": None,
        "updated_at": updated_at or datetime(2026, 6, 4, 9, 30),
    }
    row.update(overrides)
    return row


def _job_row(
    *,
    job_id: str = "job-1",
    status: str = "running",
    progress: int = 0,
    **overrides: Any,
) -> dict[str, Any]:
    """Build a fake ``backtest_jobs`` row (subset — what the stream needs)."""
    row: dict[str, Any] = {
        "job_id": job_id,
        "job_type": "walk_forward",
        "ref_id": "wf-1",
        "status": status,
        "request_json": "{}",
        "progress": progress,
        "error_message": None,
        "attempt": 1,
        "max_attempts": 1,
        "next_retry_at": None,
        "user_id": "user-1",
        "request_hash": None,
        "created_at": datetime(2026, 6, 4, 9, 30),
        "started_at": datetime(2026, 6, 4, 9, 30) if status != "queued" else None,
        "completed_at": None,
        "updated_at": datetime(2026, 6, 4, 9, 30),
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------- helpers


def _parse_sse_bytes(buf: bytes) -> list[dict[str, Any]]:
    """Decode one SSE bytes blob into a list of ``{event, id, data}`` dicts.

    Heartbeats (lines starting with ``:``) are ignored. The ``id:``
    line is captured when present (Round #1058 — Last-Event-ID plumbing).
    """
    text = buf.decode("utf-8") if isinstance(buf, bytes) else buf
    events: list[dict[str, Any]] = []
    for frame in text.split("\n\n"):
        ev: dict[str, Any] = {}
        for line in frame.split("\n"):
            if line.startswith("event:"):
                ev["event"] = line[6:].strip()
            elif line.startswith("id:"):
                ev["id"] = line[3:].strip()
            elif line.startswith("data:"):
                ev["data"] = json.loads(line[5:].strip())
        if ev:
            events.append(ev)
    return events


async def _consume_until(
    gen: Any,
    *,
    until_event: str | None = "done",
    deadline_s: float = 5.0,
) -> tuple[list[dict[str, Any]], bool]:
    """Read the generator until ``until_event`` is seen or the deadline.

    Returns ``(events, hit_done)``. ``hit_done`` is True when the
    generator emitted the target event before the deadline.

    Walk-forward generator hits the same N+1-step pattern as the
    sweep generator (4 loop iterations before the terminal frame),
    so we default the deadline to 5.0s to absorb slow CI clock drift.
    """
    events: list[dict[str, Any]] = []
    deadline = asyncio.get_event_loop().time() + deadline_s
    hit = False
    async for chunk in gen:
        events.extend(_parse_sse_bytes(chunk))
        if until_event and any(e.get("event") == until_event for e in events):
            hit = True
            break
        if asyncio.get_event_loop().time() > deadline:
            break
    return events, hit


# ---------------------------------------------------------------- autouse


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    """Speed up the SSE generator for tests.

    The stream reads the walk-forward via ``_fetch_walk_forward`` and
    the parent job from ``_JOB_STORE``. Both modules re-import the
    cadence constants from ``sse.py`` as private aliases — patching
    the originals makes the aliases pick up the test values transitively.
    """
    from getrich.apps.web.services import sse

    monkeypatch.setattr(sse, "POLL_INTERVAL_S", 0.05)
    monkeypatch.setattr(sse, "HEARTBEAT_INTERVAL_S", 0.15)


# ---------------------------------------------------------------- direct generator tests


async def test_terminal_at_connect_emits_snapshot_then_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Walk-forward whose parent job is already completed at connect time:
    snapshot + done + generator returns. No poll-loop run needed."""
    wf = _wf_row(status="completed", completed_windows=4)
    job = _job_row(status="completed", progress=100)

    async def fake_fetch_walk_forward(walk_forward_id, *, user_id):
        return wf

    async def fake_get_job_by_ref_id(ref_id, user_id=None, conn=None):
        return job

    monkeypatch.setattr(walk_forward_svc, "_fetch_walk_forward", fake_fetch_walk_forward)
    monkeypatch.setattr(walk_forward_svc._JOB_STORE, "get_job_by_ref_id", fake_get_job_by_ref_id)

    request = _FakeRequest()
    gen = walk_forward_svc.stream_walk_forward_events(
        walk_forward_id="wf-1",
        user_id="user-1",
        request=request,
    )
    events, _hit = await _consume_until(gen, until_event="done", deadline_s=1.0)

    assert [e["event"] for e in events] == ["snapshot", "done"]
    assert events[0]["data"]["status"] == "completed"
    assert events[0]["data"]["job_status"] == "completed"
    assert events[1]["data"]["status"] == "completed"
    assert events[1]["data"]["job_status"] == "completed"


async def test_active_to_terminal_emits_update_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Active walk-forward emits snapshot + N updates + done.

    The terminal frame is keyed on the *parent job*'s status, not the
    walk-forward row's status (the runner only writes the wf row AFTER
    finishing — using the wf's own status would race the writer).
    """
    wfs = [
        _wf_row(status="running", completed_windows=0, updated_at=datetime(2026, 6, 4, 9, 30, 0)),
        _wf_row(status="running", completed_windows=1, updated_at=datetime(2026, 6, 4, 9, 30, 1)),
        _wf_row(status="running", completed_windows=3, updated_at=datetime(2026, 6, 4, 9, 30, 2)),
        _wf_row(status="completed", completed_windows=4, updated_at=datetime(2026, 6, 4, 9, 30, 3)),
    ]
    jobs = [
        _job_row(status="running", progress=0, updated_at=datetime(2026, 6, 4, 9, 30, 0)),
        _job_row(status="running", progress=30, updated_at=datetime(2026, 6, 4, 9, 30, 1)),
        _job_row(status="running", progress=80, updated_at=datetime(2026, 6, 4, 9, 30, 2)),
        _job_row(status="completed", progress=100, updated_at=datetime(2026, 6, 4, 9, 30, 3)),
    ]
    idx = {"n": 0}

    async def fake_fetch_walk_forward(walk_forward_id, *, user_id):
        i = idx["n"]
        if i < len(wfs):
            idx["n"] += 1
            return wfs[i]
        return wfs[-1]

    async def fake_get_job_by_ref_id(ref_id, user_id=None, conn=None):
        i = max(0, idx["n"] - 1)  # paired with the wf read
        return jobs[i] if 0 <= i < len(jobs) else jobs[-1]

    monkeypatch.setattr(walk_forward_svc, "_fetch_walk_forward", fake_fetch_walk_forward)
    monkeypatch.setattr(walk_forward_svc._JOB_STORE, "get_job_by_ref_id", fake_get_job_by_ref_id)

    request = _FakeRequest()
    gen = walk_forward_svc.stream_walk_forward_events(
        walk_forward_id="wf-1",
        user_id="user-1",
        request=request,
    )
    events, _hit = await _consume_until(gen, until_event="done", deadline_s=5.0)

    kinds = [e["event"] for e in events]
    assert kinds[0] == "snapshot"
    assert kinds[-1] == "done"
    assert "update" in kinds
    # Final state is the terminal one — keyed on the parent job.
    assert events[-1]["data"]["job_status"] == "completed"
    assert events[-1]["data"]["progress"] == 100


async def test_cancellation_via_parent_job_emits_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation surfaces as done via the parent job's status
    (the walk-forward row's enum has no ``cancelled`` value)."""
    wf_running = _wf_row(status="running", completed_windows=2)
    job_running = _job_row(status="running", progress=50)
    job_cancelled = _job_row(status="cancelled", progress=50)
    pairs = [(wf_running, job_running), (wf_running, job_cancelled)]
    idx = {"n": 0}

    async def fake_fetch_walk_forward(walk_forward_id, *, user_id):
        i = min(idx["n"], len(pairs) - 1)
        return pairs[i][0]

    async def fake_get_job_by_ref_id(ref_id, user_id=None, conn=None):
        i = min(idx["n"], len(pairs) - 1)
        idx["n"] += 1
        return pairs[i][1]

    monkeypatch.setattr(walk_forward_svc, "_fetch_walk_forward", fake_fetch_walk_forward)
    monkeypatch.setattr(walk_forward_svc._JOB_STORE, "get_job_by_ref_id", fake_get_job_by_ref_id)

    request = _FakeRequest()
    gen = walk_forward_svc.stream_walk_forward_events(
        walk_forward_id="wf-1",
        user_id="user-1",
        request=request,
    )
    events, _hit = await _consume_until(gen, until_event="done", deadline_s=5.0)

    kinds = [e["event"] for e in events]
    assert kinds[-1] == "done"
    assert events[-1]["data"]["job_status"] == "cancelled"
    # The walk-forward's own status remains running — the cancel is a
    # top-level cancellation, not a wf-lifecycle outcome.
    assert events[-1]["data"]["status"] == "running"


async def test_heartbeat_emitted_on_idle_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When nothing changes, a :keepalive comment frame is emitted."""
    row = _wf_row(status="running")
    job = _job_row(status="running", progress=10)

    async def fake_fetch_walk_forward(walk_forward_id, *, user_id):
        return row

    async def fake_get_job_by_ref_id(ref_id, user_id=None, conn=None):
        return job

    monkeypatch.setattr(walk_forward_svc, "_fetch_walk_forward", fake_fetch_walk_forward)
    monkeypatch.setattr(walk_forward_svc._JOB_STORE, "get_job_by_ref_id", fake_get_job_by_ref_id)

    request = _FakeRequest()
    gen = walk_forward_svc.stream_walk_forward_events(
        walk_forward_id="wf-1",
        user_id="user-1",
        request=request,
    )
    # No `done` will fire. Read until a heartbeat is seen.
    raw_chunks: list[bytes] = []
    deadline = asyncio.get_event_loop().time() + 1.0
    async for chunk in gen:
        raw_chunks.append(chunk)
        if b":keepalive" in chunk:
            break
        if asyncio.get_event_loop().time() > deadline:
            break
    request.disconnect()
    # Drain the rest.
    try:
        async for _ in gen:
            pass
    except Exception:  # noqa: BLE001
        pass

    body = b"".join(raw_chunks)
    assert b":keepalive" in body


async def test_mid_stream_db_error_emits_error_then_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DB read failure mid-stream yields `event: error` then close."""
    wf = _wf_row(status="running")
    job = _job_row(status="running", progress=10)

    async def fake_fetch_walk_forward(walk_forward_id, *, user_id):
        fake_fetch_walk_forward.calls = getattr(fake_fetch_walk_forward, "calls", 0) + 1
        if fake_fetch_walk_forward.calls == 1:
            return wf
        raise RuntimeError("db unavailable")

    async def fake_get_job_by_ref_id(ref_id, user_id=None, conn=None):
        return job

    monkeypatch.setattr(walk_forward_svc, "_fetch_walk_forward", fake_fetch_walk_forward)
    monkeypatch.setattr(walk_forward_svc._JOB_STORE, "get_job_by_ref_id", fake_get_job_by_ref_id)

    request = _FakeRequest()
    gen = walk_forward_svc.stream_walk_forward_events(
        walk_forward_id="wf-1",
        user_id="user-1",
        request=request,
    )
    events, _hit = await _consume_until(gen, until_event="error", deadline_s=5.0)

    kinds = [e["event"] for e in events]
    assert "snapshot" in kinds
    assert "error" in kinds
    # Error is terminal, not done.
    assert "done" not in kinds
    error_ev = next(e for e in events if e["event"] == "error")
    assert "detail" in error_ev["data"]


async def test_wf_row_vanished_mid_stream_emits_cancelled_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A walk-forward returning None mid-stream is treated as cancelled + done."""
    wf_first = _wf_row(status="running", completed_windows=1)
    job = _job_row(status="running", progress=25)

    async def fake_fetch_walk_forward(walk_forward_id, *, user_id):
        fake_fetch_walk_forward.calls = getattr(fake_fetch_walk_forward, "calls", 0) + 1
        if fake_fetch_walk_forward.calls == 1:
            return wf_first
        return None

    async def fake_get_job_by_ref_id(ref_id, user_id=None, conn=None):
        return job

    monkeypatch.setattr(walk_forward_svc, "_fetch_walk_forward", fake_fetch_walk_forward)
    monkeypatch.setattr(walk_forward_svc._JOB_STORE, "get_job_by_ref_id", fake_get_job_by_ref_id)

    request = _FakeRequest()
    gen = walk_forward_svc.stream_walk_forward_events(
        walk_forward_id="wf-1",
        user_id="user-1",
        request=request,
    )
    events, _hit = await _consume_until(gen, until_event="done", deadline_s=5.0)

    kinds = [e["event"] for e in events]
    assert kinds[-1] == "done"
    # The synthetic cancelled frame mirrors the original wf's shape
    # so the page can render a coherent terminal row.
    assert events[-1]["data"]["status"] == "cancelled"
    assert events[-1]["data"]["walk_forward_id"] == "wf-1"
    assert events[-1]["data"]["completed_windows"] == 1


async def test_initial_wf_missing_raises_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing walk-forward at connect time → NotFound (no SSE body opened)."""
    from getrich.apps.web.errors import NotFound

    async def fake_fetch_walk_forward(walk_forward_id, *, user_id):
        return None

    monkeypatch.setattr(walk_forward_svc, "_fetch_walk_forward", fake_fetch_walk_forward)

    request = _FakeRequest()
    gen = walk_forward_svc.stream_walk_forward_events(
        walk_forward_id="missing",
        user_id="user-1",
        request=request,
    )
    with pytest.raises(NotFound):
        async for _ in gen:
            pass


async def test_client_disconnect_returns_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """request.is_disconnected() → True makes the generator return."""
    row = _wf_row(status="running")
    job = _job_row(status="running", progress=5)

    async def fake_fetch_walk_forward(walk_forward_id, *, user_id):
        return row

    async def fake_get_job_by_ref_id(ref_id, user_id=None, conn=None):
        return job

    monkeypatch.setattr(walk_forward_svc, "_fetch_walk_forward", fake_fetch_walk_forward)
    monkeypatch.setattr(walk_forward_svc._JOB_STORE, "get_job_by_ref_id", fake_get_job_by_ref_id)

    request = _FakeRequest()
    gen = walk_forward_svc.stream_walk_forward_events(
        walk_forward_id="wf-1",
        user_id="user-1",
        request=request,
    )
    # Consume the initial snapshot, then flip disconnected.
    first = await gen.__anext__()
    assert b"event: snapshot" in first
    request.disconnect()
    # Drain whatever is left — should terminate promptly.
    deadline = asyncio.get_event_loop().time() + 1.0
    async for _ in gen:
        if asyncio.get_event_loop().time() > deadline:
            pytest.fail("generator did not return after disconnect")


# ---------------------------------------------------------------- HTTP-layer tests


def _build_app(*, user_id: str | None = "user-1") -> FastAPI:
    """Build a minimal FastAPI app with the backtest-walk-forwards router + overrides."""
    from getrich.apps.web.response import register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/v1")

    async def fake_get_db():
        yield _FakeConn(_FakeCursor())

    app.dependency_overrides[get_db] = fake_get_db
    if user_id is not None:

        async def fake_require_user():
            return user_id

        app.dependency_overrides[require_user] = fake_require_user
    return app


async def test_http_cross_user_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user requesting someone else's walk-forward gets 404 (not 403)."""
    from getrich.apps.web.errors import NotFound

    async def fake_get_walk_forward(db, walk_forward_id, *, user_id):
        raise NotFound(f"walk-forward not found: {walk_forward_id}")

    # The router runs the pre-flight via `walk_forward_svc.get_walk_forward`.
    monkeypatch.setattr(walk_forward_svc, "get_walk_forward", fake_get_walk_forward)

    app = _build_app(user_id="user-2")
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/backtest-walk-forwards/wf-1/events")
    assert response.status_code == 404


async def test_http_anonymous_returns_401() -> None:
    """No override on `require_user` → 401 from the auth dependency."""
    from getrich.apps.web.response import register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/v1")

    async def fake_get_db():
        yield _FakeConn(_FakeCursor())

    app.dependency_overrides[get_db] = fake_get_db
    # Intentionally do NOT override require_user.

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/backtest-walk-forwards/wf-1/events")
    assert response.status_code == 401


def test_path_registered() -> None:
    """The new path is part of the router's public surface."""
    paths = {route.path for route in router.routes}
    assert "/backtest-walk-forwards/{walk_forward_id}/events" in paths
    events_route = next(
        r
        for r in router.routes
        if getattr(r, "path", None) == "/backtest-walk-forwards/{walk_forward_id}/events"
    )
    assert events_route.methods is not None
    assert "GET" in events_route.methods


# ---------------------------------------------------------------- Round #1058
#
# The `id:` SSE field is emitted on every data-bearing frame
# (snapshot / update / done). The router also reads the
# ``Last-Event-ID`` request header for a future replay feature;
# for now the kwarg is accepted but the snapshot is always the
# catch-up (the polling loop re-emits the current row state).


async def test_stream_emits_id_field_on_every_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All data-bearing frames carry an `id:` line set to the row's
    ``updated_at`` ISO string (the Last-Event-ID token)."""
    base = datetime(2026, 6, 4, 9, 30)
    # Drive the stream to terminal in two frames (snapshot + done)
    # by setting the parent job's status to ``completed`` at connect.
    wf = _wf_row(status="completed", completed_windows=4, updated_at=base)
    job = _job_row(status="completed", progress=100, updated_at=base)

    async def fake_fetch_walk_forward(walk_forward_id, *, user_id):
        return wf

    async def fake_get_job_by_ref_id(ref_id, user_id=None, conn=None):
        return job

    monkeypatch.setattr(walk_forward_svc, "_fetch_walk_forward", fake_fetch_walk_forward)
    monkeypatch.setattr(walk_forward_svc._JOB_STORE, "get_job_by_ref_id", fake_get_job_by_ref_id)

    request = _FakeRequest()
    events, _hit = await _consume_until(
        walk_forward_svc.stream_walk_forward_events(
            walk_forward_id="wf-1",
            user_id="user-1",
            request=request,
        ),
        until_event="done",
        deadline_s=1.0,
    )

    assert len(events) == 2
    expected_id = base.isoformat()
    for ev in events:
        assert ev.get("id") == expected_id, (
            f"frame {ev['event']!r} missing id: line (got {ev.get('id')!r})"
        )


# ---- Round #1063: pg_notify listener wakeup ----


class _FakeListener:
    """In-process stand-in for ``BacktestJobListener``.

    ``notify`` is "sticky" — calling it before ``subscribe`` arms a
    pending flag so the next ``subscribe`` returns an event that is
    already set. Mirrors the production contract (the worker
    NOTIFY happens only after the row is visible, and the LISTEN
    was already established at app startup).
    """

    def __init__(self) -> None:
        self._events: dict[str, asyncio.Event] = {}
        self._pending: set[str] = set()

    def subscribe(self, job_id: str) -> asyncio.Event:
        ev = self._events.get(job_id)
        if ev is None:
            ev = asyncio.Event()
            self._events[job_id] = ev
        if job_id in self._pending:
            ev.set()
            self._pending.discard(job_id)
        return ev

    def unsubscribe(self, job_id: str) -> None:
        self._events.pop(job_id, None)
        self._pending.discard(job_id)

    def notify(self, job_id: str) -> None:
        ev = self._events.get(job_id)
        if ev is not None:
            ev.set()
        else:
            self._pending.add(job_id)


async def test_listener_wakes_walk_forward_generator_within_50ms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the listener fires ``notify(parent_job_id)``, the
    walk-forward generator wakes up and re-reads the parent job row
    within ~50ms.
    """
    fake_listener = _FakeListener()
    monkeypatch.setattr(walk_forward_svc, "_LISTENER", fake_listener)

    base = datetime(2026, 6, 5, 10, 0, 0)
    wf = _wf_row(status="running", updated_at=base)
    jobs = [
        _job_row(status="running", progress=0, updated_at=base),
        _job_row(status="running", progress=50, updated_at=base + timedelta(seconds=1)),
        _job_row(status="completed", progress=100, updated_at=base + timedelta(seconds=2)),
    ]
    job_idx = {"n": 0}

    async def fake_fetch_walk_forward(walk_forward_id, user_id=None):
        return wf

    async def fake_get_job_by_ref_id(ref_id, user_id=None, conn=None):
        r = jobs[min(job_idx["n"], len(jobs) - 1)]
        job_idx["n"] += 1
        return r

    monkeypatch.setattr(walk_forward_svc, "_fetch_walk_forward", fake_fetch_walk_forward)
    monkeypatch.setattr(walk_forward_svc._JOB_STORE, "get_job_by_ref_id", fake_get_job_by_ref_id)

    request = _FakeRequest()
    gen = walk_forward_svc.stream_walk_forward_events(
        walk_forward_id="wf-1", user_id="user-1", request=request
    )
    snapshot = await gen.__anext__()
    assert b"event: snapshot" in snapshot

    start = asyncio.get_event_loop().time()
    fake_listener.notify("job-1")
    update_frame = await asyncio.wait_for(gen.__anext__(), timeout=0.5)
    elapsed = asyncio.get_event_loop().time() - start
    assert b"event: update" in update_frame
    assert elapsed < 0.2, f"notify→update latency too high: {elapsed * 1000:.0f}ms"

    fake_listener.notify("job-1")
    rest, _hit = await _consume_until(gen, until_event="done", deadline_s=1.0)
    assert rest[-1]["event"] == "done"


async def test_walk_forward_generator_degrades_without_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``_LISTENER`` is None, the walk-forward generator falls
    back to the 1Hz polling safety net. Frames still arrive.
    """
    monkeypatch.setattr(walk_forward_svc, "_LISTENER", None)

    base = datetime(2026, 6, 5, 10, 0, 0)
    wf = _wf_row(status="running", updated_at=base)
    jobs = [
        _job_row(status="running", progress=0, updated_at=base),
        _job_row(status="completed", progress=100, updated_at=base + timedelta(seconds=1)),
    ]
    job_idx = {"n": 0}

    async def fake_fetch_walk_forward(walk_forward_id, user_id=None):
        return wf

    async def fake_get_job_by_ref_id(ref_id, user_id=None, conn=None):
        r = jobs[min(job_idx["n"], len(jobs) - 1)]
        job_idx["n"] += 1
        return r

    monkeypatch.setattr(walk_forward_svc, "_fetch_walk_forward", fake_fetch_walk_forward)
    monkeypatch.setattr(walk_forward_svc._JOB_STORE, "get_job_by_ref_id", fake_get_job_by_ref_id)

    gen = walk_forward_svc.stream_walk_forward_events(
        walk_forward_id="wf-1", user_id="user-1", request=_FakeRequest()
    )
    events, _hit = await _consume_until(gen, until_event="done", deadline_s=2.0)
    assert [e["event"] for e in events] == ["snapshot", "update", "done"]
