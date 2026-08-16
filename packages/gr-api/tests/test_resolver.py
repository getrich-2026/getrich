"""Tests for the resolver service.

`services.resolver` translates human-facing codes (e.g. `STR_FUT_001`,
`SIG_20260415_001`) to internal UUIDs. The functions are pure
single-SELECT lookups with a `NotFound` raise on miss.
"""

from __future__ import annotations

from typing import Any

import pytest
from gr_api.errors import NotFound
from gr_api.services.resolver import (
    signal_code_to_id,
    strategy_code_to_id,
)


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []
        self._next_row: dict[str, Any] | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def execute(self, sql, params=None):
        self.executed.append((sql.strip(), params))

    async def fetchone(self):
        return self._next_row

    def push_row(self, row: dict[str, Any] | None) -> None:
        self._next_row = row


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self):
        return self._cursor


# ---------------------------------------------------------------------------
# strategy_code_to_id
# ---------------------------------------------------------------------------


async def test_strategy_code_to_id_returns_uuid_string() -> None:
    """Happy path: a row is found and the UUID is returned as a
    plain string (so the router can pass it to other services).
    """
    cursor = _FakeCursor()
    cursor.push_row({"id": "550e8400-e29b-41d4-a716-446655440000"})
    conn = _FakeConn(cursor)

    result = await strategy_code_to_id(
        conn,  # type: ignore[arg-type]
        strategy_code="STR_FUT_001",
    )

    assert result == "550e8400-e29b-41d4-a716-446655440000"
    # SQL is the canonical strategies-by-code lookup.
    assert len(cursor.executed) == 1
    sql, params = cursor.executed[0]
    assert sql == "SELECT id FROM strategies WHERE strategy_code = %s"
    assert params == ("STR_FUT_001",)


async def test_strategy_code_to_id_raises_not_found_for_missing_code() -> None:
    cursor = _FakeCursor()
    cursor.push_row(None)
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        await strategy_code_to_id(
            conn,  # type: ignore[arg-type]
            strategy_code="NOPE",
        )


async def test_strategy_code_to_id_coerces_uuid_to_string() -> None:
    """If psycopg returns the UUID column as a `uuid.UUID` instance
    (depending on the type adapter), the service still produces a
    string. This guards against an accidental removal of `str(...)`.
    """
    import uuid

    cursor = _FakeCursor()
    cursor.push_row({"id": uuid.UUID("11111111-2222-3333-4444-555555555555")})
    conn = _FakeConn(cursor)

    result = await strategy_code_to_id(
        conn,  # type: ignore[arg-type]
        strategy_code="STR_FUT_001",
    )

    assert isinstance(result, str)
    assert result == "11111111-2222-3333-4444-555555555555"


# ---------------------------------------------------------------------------
# signal_code_to_id
# ---------------------------------------------------------------------------


async def test_signal_code_to_id_returns_uuid_string() -> None:
    cursor = _FakeCursor()
    cursor.push_row({"id": "abcdef00-1234-5678-9abc-def012345678"})
    conn = _FakeConn(cursor)

    result = await signal_code_to_id(
        conn,  # type: ignore[arg-type]
        signal_code="SIG_20260501_001",
    )

    assert result == "abcdef00-1234-5678-9abc-def012345678"
    sql, params = cursor.executed[0]
    assert sql == "SELECT id FROM signals WHERE signal_code = %s"
    assert params == ("SIG_20260501_001",)


async def test_signal_code_to_id_raises_not_found_for_missing_code() -> None:
    cursor = _FakeCursor()
    cursor.push_row(None)
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        await signal_code_to_id(
            conn,  # type: ignore[arg-type]
            signal_code="SIG_NOPE",
        )
