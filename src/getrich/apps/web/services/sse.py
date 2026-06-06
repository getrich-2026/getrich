"""Shared SSE (Server-Sent Events) encoding helpers.

Centralises the frame encoder, heartbeat line, and polling/heartbeat
cadence constants so multiple service generators (``stream_job_events``,
``stream_sweep_events``, ``stream_walk_forward_events``, ...) can share
the same wire format and timing without copy-paste.

History
-------
These helpers were originally defined as private symbols on
``backtest_job.py``. Round #1061 (sweep+wf dedicated events endpoints)
promoted them to this shared module so the new stream generators
could reuse the same encoder and cadence without reaching across
service modules.
"""

from __future__ import annotations

import json
from typing import Any


# Polling cadence for the SSE generators. 1 Hz is a balance between
# progress-bar smoothness and DB load; the runner throttles its own
# writes at 5%-boundaries, so a faster poll does not see more writes.
POLL_INTERVAL_S: float = 1.0

# Heartbeat cadence. The SSE spec uses a comment line (``:keepalive``)
# to keep idle connections alive across reverse proxies. We reset
# the clock whenever a real event is emitted, so an actively-changing
# job never sends heartbeats.
HEARTBEAT_INTERVAL_S: float = 15.0

# SSE comment line; ignored by EventSource but counted by proxies.
SSE_HEARTBEAT: bytes = b":keepalive\n\n"

# Statuses that mean the row is done and the generator should close.
# Kept module-level (not on the job generator) so the sweep and
# walk-forward generators can reuse the same tri-state.
TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"completed", "failed", "cancelled"},
)


def sse_frame(
    event: str,
    data: Any,
    *,
    event_id: str | None = None,
) -> bytes:
    """Encode one SSE event with a JSON ``data`` payload.

    Format::

        event: <event>
        id: <event_id>          # only if ``event_id`` is not None
        data: <json>

    (blank line terminator)

    The optional ``id:`` line is the SSE "last event id" — the
    EventSource spec says the client MUST send it back as the
    ``Last-Event-ID`` request header on reconnect. We use the row's
    ``updated_at`` ISO string as the token (see Round #1058 plan).

    ``default=str`` lets ``datetime`` values round-trip without
    requiring a custom encoder.
    """
    payload = json.dumps(data, default=str)
    id_line = f"id: {event_id}\n" if event_id else ""
    return f"event: {event}\n{id_line}data: {payload}\n\n".encode()


__all__ = [
    "HEARTBEAT_INTERVAL_S",
    "POLL_INTERVAL_S",
    "SSE_HEARTBEAT",
    "TERMINAL_STATUSES",
    "sse_frame",
]
