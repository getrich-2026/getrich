"""Tests for the shared SSE encoding helpers.

`services.sse` is the lowest-level helper used by 3 service generators
(``backtest_job.stream_job_events``, ``backtest_sweep.stream_sweep_events``,
``backtest_walk_forward.stream_walk_forward_events``). It exports:

- ``sse_frame(event, data, event_id=None)`` — encode one event
- ``SSE_HEARTBEAT`` — the keepalive comment bytes
- ``POLL_INTERVAL_S`` / ``HEARTBEAT_INTERVAL_S`` — timing constants
- ``TERMINAL_STATUSES`` — frozenset of "done" job states

These are pure functions (no DB), so the tests are tiny.
"""

from __future__ import annotations

import json

from getrich.apps.web.services.sse import (
    HEARTBEAT_INTERVAL_S,
    POLL_INTERVAL_S,
    SSE_HEARTBEAT,
    TERMINAL_STATUSES,
    sse_frame,
)


# ---------------------------------------------------------------------------
# sse_frame
# ---------------------------------------------------------------------------


class TestSseFrame:
    def test_basic_event_no_id(self) -> None:
        """event + data lines, blank line terminator, no id."""
        result = sse_frame("status", {"state": "running"})
        assert result == b'event: status\ndata: {"state": "running"}\n\n'

    def test_event_with_id(self) -> None:
        """id: line emitted between event: and data: when event_id given."""
        result = sse_frame(
            "status", {"state": "running"}, event_id="evt-2026-01-01T00:00:00Z",
        )
        # The id: line must be the second line (between event: and data:)
        lines = result.decode().split("\n")
        assert lines[0] == "event: status"
        assert lines[1] == "id: evt-2026-01-01T00:00:00Z"
        assert lines[2] == 'data: {"state": "running"}'
        assert lines[3] == ""  # blank line terminator
        assert lines[4] == ""  # final newline

    def test_data_serialised_as_json(self) -> None:
        """Nested dict, list, string — JSON round-trip."""
        result = sse_frame("e", {"a": 1, "b": [1, 2, 3], "c": "x"})
        payload = json.loads(result.decode().split("data: ", 1)[1].split("\n")[0])
        assert payload == {"a": 1, "b": [1, 2, 3], "c": "x"}

    def test_datetime_serialised_via_default_str(self) -> None:
        """datetime values go through ``json.dumps(..., default=str)``."""
        from datetime import datetime
        result = sse_frame("e", {"ts": datetime(2026, 1, 1, 12, 0, 0)})
        # ISO string format
        assert '"ts": "2026-01-01 12:00:00"' in result.decode()

    def test_empty_data(self) -> None:
        """Empty dict / list / string still serialise."""
        assert b"data: {}" in sse_frame("e", {})
        assert b"data: []" in sse_frame("e", [])
        assert b'data: ""' in sse_frame("e", "")

    def test_returns_bytes(self) -> None:
        """sse_frame always returns bytes (encoded utf-8 by default)."""
        assert isinstance(sse_frame("e", {"x": 1}), bytes)
        # Unicode in data is preserved (json.dumps escapes as \uXXXX by
        # default, which is still valid UTF-8 when wrapped in the SSE
        # frame). The wire format survives round-trip.
        result = sse_frame("e", {"msg": "你好"})
        assert isinstance(result, bytes)
        assert result.decode("utf-8")  # must be valid UTF-8


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    def test_heartbeat_bytes(self) -> None:
        """Heartbeat is a single SSE comment line, blank-line terminated."""
        assert SSE_HEARTBEAT == b":keepalive\n\n"
        # First line is a comment (starts with ':')
        assert SSE_HEARTBEAT.startswith(b":")

    def test_terminal_statuses(self) -> None:
        """TERMINAL_STATUSES is the canonical tri-state done set."""
        assert TERMINAL_STATUSES == frozenset({"completed", "failed", "cancelled"})
        # "running" is NOT terminal
        assert "running" not in TERMINAL_STATUSES
        assert "pending" not in TERMINAL_STATUSES

    def test_poll_interval_is_1s(self) -> None:
        """POLL_INTERVAL_S = 1.0 (1 Hz polling cadence)."""
        assert POLL_INTERVAL_S == 1.0

    def test_heartbeat_interval_is_15s(self) -> None:
        """HEARTBEAT_INTERVAL_S = 15.0 (long enough to not be chatty)."""
        assert HEARTBEAT_INTERVAL_S == 15.0
