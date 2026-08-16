"""Tests for the GET /backtest-jobs/{job_id}/events SSE endpoint.

The endpoint streams lifecycle events for one job:

* ``event: snapshot`` (first frame)
* zero or more ``event: update``
* ``event: done`` (when status becomes terminal)
* close

Plus ``:keepalive`` comment frames every 15 s on idle connections.
The generator polls the DB at 1 Hz; this file monkeypatches the
constants to keep test runs fast.

Most tests in this file exercise the async generator
``job_svc.stream_job_events`` directly with a fake ``Request``.
ASGITransport does not faithfully simulate client disconnects, so a
pure call-and-iterate approach is the most reliable way to assert
event sequencing. The router-level HTTP tests are kept narrow (404 on
cross-user, 401 on anonymous) since they don't rely on the stream
lifecycle.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from gr_api.deps import get_db, require_user
from gr_api.routers.backtest_jobs import router
from gr_api.services import backtest_job as job_svc
from httpx import ASGITransport


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------- fixtures


class _FakeCursor:
    def __init__(
        self,
        *,
        fetchone: dict[str, Any] | None = None,
        fetchone_seq: list[dict[str, Any] | None] | None = None,
    ) -> None:
        self._fetchone = fetchone
        self._fetchone_seq = fetchone_seq
        self._idx = 0
        self.executed: list[tuple[str, dict[str, Any] | None]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, sql: str, params: dict[str, Any] | None = None) -> None:
        self.executed.append((sql, params))

    async def fetchone(self) -> dict[str, Any] | None:
        if self._fetchone_seq is not None:
            if self._idx >= len(self._fetchone_seq):
                return None
            value = self._fetchone_seq[self._idx]
            self._idx += 1
            return value
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


def _job_row(
    *,
    job_id: str = "job-1",
    status: str = "running",
    progress: int = 0,
    user_id: str | None = "user-1",
    updated_at: datetime | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "job_id": job_id,
        "job_type": "backtest",
        "ref_id": "run-1",
        "status": status,
        "request_json": "{}",
        "progress": progress,
        "error_message": None,
        "attempt": 1,
        "max_attempts": 1,
        "next_retry_at": None,
        "user_id": user_id,
        "request_hash": None,
        "retry_base_seconds": None,
        "retry_cap_seconds": None,
        "retry_jitter_pct": None,
        "created_at": datetime(2026, 6, 4, 9, 30),
        "started_at": datetime(2026, 6, 4, 9, 30) if status != "queued" else None,
        "completed_at": None,
        "updated_at": updated_at or datetime(2026, 6, 4, 9, 30),
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
    deadline_s: float = 2.0,
) -> tuple[list[dict[str, Any]], bool]:
    """Read the generator until ``until_event`` is seen or the deadline.

    Returns ``(events, hit_done)``. ``hit_done`` is True when the
    generator emitted the target event before the deadline.
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


# ---------------------------------------------------------------- tests


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    """Speed up the SSE generator for tests."""
    monkeypatch.setattr(job_svc, "_POLL_INTERVAL_S", 0.05)
    monkeypatch.setattr(job_svc, "_HEARTBEAT_INTERVAL_S", 0.15)


# ---- direct generator tests (no HTTP layer) ----


async def test_terminal_at_connect_emits_snapshot_then_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Job already finished → snapshot + done + generator returns."""
    row = _job_row(status="completed", progress=100)

    async def fake_get_job(job_id, user_id=None, conn=None):
        return row

    monkeypatch.setattr(job_svc._STORE, "get_job", fake_get_job)

    request = _FakeRequest()
    gen = job_svc.stream_job_events(job_id="job-1", user_id="user-1", request=request)
    events, _hit = await _consume_until(gen, until_event="done", deadline_s=1.0)

    assert [e["event"] for e in events] == ["snapshot", "done"]
    assert events[0]["data"]["status"] == "completed"
    assert events[1]["data"]["status"] == "completed"


async def test_active_to_terminal_emits_update_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Active job emits snapshot + N updates + done as the runner writes."""
    base = datetime(2026, 6, 4, 9, 30)
    rows = [
        _job_row(status="queued", progress=0, updated_at=base),
        _job_row(status="running", progress=30, updated_at=base),
        _job_row(status="running", progress=60, updated_at=base),
        _job_row(status="completed", progress=100, updated_at=base),
    ]
    idx = {"n": 0}

    async def fake_get_job(job_id, user_id=None, conn=None):
        if idx["n"] < len(rows):
            r = rows[idx["n"]]
            idx["n"] += 1
            return r
        return rows[-1]

    monkeypatch.setattr(job_svc._STORE, "get_job", fake_get_job)

    request = _FakeRequest()
    gen = job_svc.stream_job_events(job_id="job-1", user_id="user-1", request=request)
    events, _hit = await _consume_until(gen, until_event="done", deadline_s=2.0)

    kinds = [e["event"] for e in events]
    assert kinds[0] == "snapshot"
    assert kinds[-1] == "done"
    # At least one update before done.
    assert "update" in kinds
    # Final state is the terminal one.
    assert events[-1]["data"]["progress"] == 100
    assert events[-1]["data"]["status"] == "completed"


async def test_heartbeat_emitted_on_idle_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When nothing changes, a :keepalive comment frame is emitted."""
    row = _job_row(status="running", progress=0)

    async def fake_get_job(job_id, user_id=None, conn=None):
        return row

    monkeypatch.setattr(job_svc._STORE, "get_job", fake_get_job)

    request = _FakeRequest()
    gen = job_svc.stream_job_events(job_id="job-1", user_id="user-1", request=request)
    # No `done` will fire (job stays in running). Read until heartbeat
    # is seen or the deadline.
    raw_chunks: list[bytes] = []
    deadline = asyncio.get_event_loop().time() + 1.0
    async for chunk in gen:
        raw_chunks.append(chunk)
        if b":keepalive" in chunk:
            break
        if asyncio.get_event_loop().time() > deadline:
            break
    # Force the generator to exit.
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
    row_first = _job_row(status="running", progress=10)

    async def fake_get_job(job_id, user_id=None, conn=None):
        fake_get_job.calls = getattr(fake_get_job, "calls", 0) + 1
        if fake_get_job.calls == 1:
            return row_first
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(job_svc._STORE, "get_job", fake_get_job)

    request = _FakeRequest()
    gen = job_svc.stream_job_events(job_id="job-1", user_id="user-1", request=request)
    events, _hit = await _consume_until(gen, until_event="error", deadline_s=2.0)

    kinds = [e["event"] for e in events]
    assert "snapshot" in kinds
    assert "error" in kinds
    # Error is terminal, not done.
    assert "done" not in kinds
    error_ev = next(e for e in events if e["event"] == "error")
    assert "detail" in error_ev["data"]


async def test_row_deleted_mid_stream_emits_cancelled_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A row returning None mid-stream is treated as cancelled + done."""
    row_first = _job_row(status="running", progress=10)

    async def fake_get_job(job_id, user_id=None, conn=None):
        fake_get_job.calls = getattr(fake_get_job, "calls", 0) + 1
        if fake_get_job.calls == 1:
            return row_first
        return None

    monkeypatch.setattr(job_svc._STORE, "get_job", fake_get_job)

    request = _FakeRequest()
    gen = job_svc.stream_job_events(job_id="job-1", user_id="user-1", request=request)
    events, _hit = await _consume_until(gen, until_event="done", deadline_s=2.0)

    kinds = [e["event"] for e in events]
    assert kinds[-1] == "done"
    assert events[-1]["data"]["status"] == "cancelled"


async def test_initial_row_missing_raises_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing row at connect time → NotFound (no SSE body opened)."""
    from gr_api.errors import NotFound

    async def fake_get_job(job_id, user_id=None, conn=None):
        return None

    monkeypatch.setattr(job_svc._STORE, "get_job", fake_get_job)

    request = _FakeRequest()
    gen = job_svc.stream_job_events(job_id="missing", user_id="user-1", request=request)
    with pytest.raises(NotFound):
        async for _ in gen:
            pass


async def test_client_disconnect_returns_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """request.is_disconnected() → True makes the generator return."""
    row = _job_row(status="running", progress=0)

    async def fake_get_job(job_id, user_id=None, conn=None):
        return row

    monkeypatch.setattr(job_svc._STORE, "get_job", fake_get_job)

    request = _FakeRequest()
    gen = job_svc.stream_job_events(job_id="job-1", user_id="user-1", request=request)
    # Consume the initial snapshot, then flip disconnected.
    first = await gen.__anext__()
    assert b"event: snapshot" in first
    request.disconnect()
    # Drain whatever is left — should terminate promptly.
    deadline = asyncio.get_event_loop().time() + 1.0
    async for _ in gen:
        if asyncio.get_event_loop().time() > deadline:
            pytest.fail("generator did not return after disconnect")


# ---- HTTP-layer tests (router + auth) ----


def _build_app(*, user_id: str | None = "user-1") -> FastAPI:
    """Build a minimal FastAPI app with the backtest-jobs router + overrides.

    Mirrors the production routing layout: the router is mounted under
    the ``/v1`` prefix so the test URLs match the on-the-wire path
    ``/v1/backtest-jobs/{job_id}/events``. Exception handlers are
    registered so ``NotFound`` / ``Unauthorized`` surface as JSON
    responses with the right HTTP status, mirroring production
    behavior in ``main.create_app()``.
    """
    from gr_api.response import register_exception_handlers

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
    """A user requesting someone else's job gets 404 (not 403)."""

    async def fake_get_job(job_id, user_id=None, conn=None):
        return None

    monkeypatch.setattr(job_svc._STORE, "get_job", fake_get_job)

    app = _build_app(user_id="user-2")
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/backtest-jobs/job-1/events")
    assert response.status_code == 404


async def test_http_anonymous_returns_401() -> None:
    """No override on `require_user` → 401 from the auth dependency."""
    from gr_api.response import register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/v1")

    async def fake_get_db():
        yield _FakeConn(_FakeCursor())

    app.dependency_overrides[get_db] = fake_get_db
    # Intentionally do NOT override require_user.

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/backtest-jobs/job-1/events")
    assert response.status_code == 401


def test_path_registered() -> None:
    """The new path is part of the router's public surface."""
    paths = {route.path for route in router.routes}
    assert "/backtest-jobs/{job_id}/events" in paths
    events_route = next(
        r for r in router.routes if getattr(r, "path", None) == "/backtest-jobs/{job_id}/events"
    )
    assert events_route.methods is not None
    assert "GET" in events_route.methods


# ---------------------------------------------------------------- Round #1058
#
# The `id:` SSE field is now emitted on every data-bearing frame
# (snapshot / update / done). The router also reads the
# ``Last-Event-ID`` request header for a future replay feature;
# for now the kwarg is accepted but the snapshot is always the
# catch-up (the polling loop re-emits the current row state).


def test_sse_frame_includes_id_field_when_event_id_given() -> None:
    """`_sse_frame("snapshot", data, event_id="...")` produces
    a frame with an `id:` line BETWEEN `event:` and `data:` —
    the order required by the SSE spec."""
    from gr_api.services.backtest_job import _sse_frame

    payload = {"job_id": "j-1", "updated_at": "2026-06-05T10:00:00"}
    out = _sse_frame("snapshot", payload, event_id="2026-06-05T10:00:00")
    text = out.decode("utf-8")

    # The three required lines plus the blank terminator.
    assert "event: snapshot\n" in text
    assert "id: 2026-06-05T10:00:00\n" in text
    assert "data: " in text
    assert text.endswith("\n\n")
    # Order matters: event → id → data (SSE spec).
    event_idx = text.index("event: snapshot")
    id_idx = text.index("id: 2026-06-05T10:00:00")
    data_idx = text.index("data: ")
    assert event_idx < id_idx < data_idx


def test_sse_frame_omits_id_line_when_event_id_is_none() -> None:
    """Without an event_id, the frame is the legacy 2-line shape —
    backward-compatible with clients that don't speak the id field."""
    from gr_api.services.backtest_job import _sse_frame

    out = _sse_frame("snapshot", {"job_id": "j-1"})
    text = out.decode("utf-8")
    assert "id:" not in text
    assert "event: snapshot" in text
    assert "data: " in text


async def test_stream_emits_id_on_every_data_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """On a healthy stream with three distinct row states
    (initial → progress → terminal), every parsed data event
    carries a non-empty `id` matching the row's `updated_at`."""
    rows = [
        _job_row(status="running", progress=10, updated_at=datetime(2026, 6, 5, 10, 0, 0)),
        _job_row(status="running", progress=20, updated_at=datetime(2026, 6, 5, 10, 0, 1)),
        _job_row(status="completed", progress=100, updated_at=datetime(2026, 6, 5, 10, 0, 2)),
    ]
    idx = {"n": 0}

    async def fake_get_job(job_id, user_id=None, conn=None):
        if idx["n"] < len(rows):
            r = rows[idx["n"]]
            idx["n"] += 1
            return r
        return rows[-1]

    monkeypatch.setattr(job_svc._STORE, "get_job", fake_get_job)

    gen = job_svc.stream_job_events(job_id="job-1", user_id="user-1", request=_FakeRequest())
    events, _hit = await _consume_until(gen, until_event="done", deadline_s=2.0)

    # snapshot + 2 updates (one per changed row) + done.
    assert [e["event"] for e in events] == ["snapshot", "update", "update", "done"]
    # Every frame carries an id; the id matches the row's updated_at.
    expected_ids = [
        "2026-06-05T10:00:00",
        "2026-06-05T10:00:01",
        "2026-06-05T10:00:02",
        "2026-06-05T10:00:02",  # done reuses the last seen frame id
    ]
    actual_ids = [e.get("id") for e in events]
    assert actual_ids == expected_ids


async def test_stream_accepts_last_event_id_kwarg_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`last_event_id` is plumbed end-to-end. The current
    implementation does NOT replay — it still emits the current
    snapshot and continues. This test pins that the kwarg is
    accepted and the stream behaves identically to a fresh
    connect (modulo the `id` field which is always present)."""
    rows = [
        _job_row(status="running", progress=10, updated_at=datetime(2026, 6, 5, 10, 0, 0)),
        _job_row(status="completed", progress=100, updated_at=datetime(2026, 6, 5, 10, 0, 1)),
    ]
    idx = {"n": 0}

    async def fake_get_job(job_id, user_id=None, conn=None):
        if idx["n"] < len(rows):
            r = rows[idx["n"]]
            idx["n"] += 1
            return r
        return rows[-1]

    monkeypatch.setattr(job_svc._STORE, "get_job", fake_get_job)

    gen = job_svc.stream_job_events(
        job_id="job-1",
        user_id="user-1",
        request=_FakeRequest(),
        last_event_id="2026-06-05T09:00:00",  # older than current row
    )
    events, _hit = await _consume_until(gen, until_event="done", deadline_s=2.0)

    # A stale last_event_id still produces a normal snapshot.
    assert [e["event"] for e in events] == ["snapshot", "update", "done"]
    assert all(e.get("id") for e in events)


# ---- Round #1063: pg_notify listener wakeup ----


class _FakeListener:
    """In-process stand-in for ``BacktestJobListener``.

    Only the methods the SSE generator actually calls are
    implemented. ``notify(job_id)`` is the test injection point —
    calling it sets the event for that job so the generator's
    ``wait_for`` returns immediately.

    ``notify`` is "sticky" — calling it before ``subscribe`` arms a
    pending flag so the next ``subscribe`` returns an event that is
    already set. This mirrors the production contract (the worker
    NOTIFY happens only after the row is visible, and the LISTEN was
    already established at app startup).
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


async def test_listener_wakes_generator_within_50ms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the listener fires ``notify(job_id)``, the SSE generator
    wakes up and re-reads the row within ~50ms (vs. up to 1s without
    the listener).
    """
    # Replace the module-level listener with our fake. The lifespan
    # would normally set this; tests don't run the lifespan, so the
    # default is None and the generator would poll. We inject here
    # to exercise the listener path.
    fake_listener = _FakeListener()
    monkeypatch.setattr(job_svc, "_LISTENER", fake_listener)

    t0 = datetime(2026, 6, 5, 10, 0, 0)
    rows = [
        _job_row(status="running", progress=0, updated_at=t0),
        _job_row(status="running", progress=50, updated_at=t0 + timedelta(seconds=1)),
        _job_row(status="completed", progress=100, updated_at=t0 + timedelta(seconds=2)),
    ]
    idx = {"n": 0}

    async def fake_get_job(job_id, user_id=None, conn=None):
        r = rows[min(idx["n"], len(rows) - 1)]
        idx["n"] += 1
        return r

    monkeypatch.setattr(job_svc._STORE, "get_job", fake_get_job)

    request = _FakeRequest()
    gen = job_svc.stream_job_events(job_id="job-1", user_id="user-1", request=request)
    # Consume the snapshot first.
    snapshot = await gen.__anext__()
    assert b"event: snapshot" in snapshot

    # Now drive a notify; the generator should wake up, see the
    # changed row, and yield an `update` frame within 50ms.
    start = asyncio.get_event_loop().time()
    fake_listener.notify("job-1")
    update_frame = await asyncio.wait_for(gen.__anext__(), timeout=0.5)
    elapsed = asyncio.get_event_loop().time() - start
    assert b"event: update" in update_frame
    # The notify→frame latency should be sub-50ms in practice;
    # allow 200ms headroom for CI variance.
    assert elapsed < 0.2, f"notify→update latency too high: {elapsed * 1000:.0f}ms"

    # Drive a second notify so the generator reaches the terminal
    # 100% row and yields update + done. Use ``_consume_until`` to
    # read past both frames.
    fake_listener.notify("job-1")
    rest, _hit = await _consume_until(gen, until_event="done", deadline_s=1.0)
    kinds = [e["event"] for e in rest]
    assert kinds[-1] == "done"
    # At least one update was emitted between the first notify and done.
    assert "update" in kinds


async def test_generator_degrades_without_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``_LISTENER`` is None, the generator falls back to the
    1Hz polling safety net. Frames still arrive; the latency just
    matches the poll interval (50ms in tests via ``_fast_poll``).
    """
    monkeypatch.setattr(job_svc, "_LISTENER", None)

    t0 = datetime(2026, 6, 5, 10, 0, 0)
    rows = [
        _job_row(status="running", progress=0, updated_at=t0),
        _job_row(status="completed", progress=100, updated_at=t0 + timedelta(seconds=1)),
    ]
    idx = {"n": 0}

    async def fake_get_job(job_id, user_id=None, conn=None):
        r = rows[min(idx["n"], len(rows) - 1)]
        idx["n"] += 1
        return r

    monkeypatch.setattr(job_svc._STORE, "get_job", fake_get_job)

    gen = job_svc.stream_job_events(job_id="job-1", user_id="user-1", request=_FakeRequest())
    events, _hit = await _consume_until(gen, until_event="done", deadline_s=2.0)
    assert [e["event"] for e in events] == ["snapshot", "update", "done"]
