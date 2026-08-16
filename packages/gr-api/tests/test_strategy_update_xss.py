"""Integration tests for `update_strategy` HTML sanitization and IDOR.

Verifies that the service-layer XSS defense is wired correctly: any
`detail_html` value passed to `update_strategy` is run through
`services.sanitize.normalize_detail_html` before reaching the database.

Also covers the IDOR guard: only the strategy's `author_id` may call
`update_strategy` — other users get 403.
"""

from __future__ import annotations

from typing import Any

import pytest
from gr_api.errors import Forbidden, NotFound
from gr_api.services.sanitize import normalize_detail_html
from gr_api.services.strategy import update_strategy


# `anyio` is the project's async test runner (no `pytest-asyncio` in
# this codebase). `pytestmark` applies the marker to every test in the
# module.
pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Mock async cursor that returns a sequence of rows.

    The IDOR-guard `assert_strategy_owner` runs ONE SELECT before
    `update_strategy`'s UPDATE. The post-update `get_strategy_detail`
    re-read runs three more SELECTs (main row / tags / users). The
    cursor's `fetchone`/`fetchall` dispatch by call count lets us
    inject different rows for each.
    """

    def __init__(
        self,
        *,
        rows_per_call: list[Any] | None = None,
        default_all: list[dict[str, Any]] | None = None,
    ) -> None:
        # Index -> row. Index 0 is consumed by assert_strategy_owner
        # (None means strategy_id doesn't exist). Indices 1+ consumed
        # by the UPDATE (`fetchone` returns the strategy_code row) and
        # by get_strategy_detail (tags / users / main row).
        self._rows_per_call = list(rows_per_call or [])
        self._default_all = list(default_all or [])
        self._call_idx = 0
        self.executed: list[tuple[str, dict[str, Any] | None]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def execute(self, sql, params=None):
        self.executed.append((sql.strip(), params))
        self._call_idx += 1

    async def fetchone(self):
        if self._call_idx - 1 < len(self._rows_per_call):
            return self._rows_per_call[self._call_idx - 1]
        return None

    async def fetchall(self):
        return list(self._default_all)


class _FakeConn:
    """Mock async connection. Re-uses the same cursor for every
    `cursor()` call — the fake cursor counts `execute()` calls so it
    can return different rows on successive fetches."""

    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self):
        return self._cursor


async def _stub_get_strategy_detail(_db, _strategy_id: str) -> dict[str, Any]:
    """Stub for `get_strategy_detail` — return a known dict so
    `update_strategy` has something to return. `async` because the real
    function is awaited by the service.
    """
    return {
        "id": _strategy_id,
        "strategy_code": "STR_FUT_001",
        "detail_html": "<stub>",
        "name": "Stub",
    }


# ---------------------------------------------------------------------------
# Sanitize
# ---------------------------------------------------------------------------


async def test_update_strategy_sanitizes_detail_html(monkeypatch) -> None:
    """A malicious `detail_html` payload is normalized before reaching
    the SQL parameter dict.
    """
    monkeypatch.setattr(
        "gr_api.services.strategy.get_strategy_detail",
        _stub_get_strategy_detail,
    )

    # Rows by call idx:
    #   0 (assert_strategy_owner SELECT) -> {author_id: "u-owner"}
    #   1 (UPDATE RETURNING)              -> {strategy_code: ...}
    #   2..3 (get_strategy_detail SELECTs: tags, users)
    #   4 (get_strategy_detail main row)  -> None (we don't care)
    cursor = _FakeCursor(
        rows_per_call=[
            {"author_id": "u-owner"},  # assert_strategy_owner
            {"strategy_code": "STR_FUT_001"},  # UPDATE RETURNING
            None,  # tags fetchall
            None,  # users fetchone
            None,  # main row
        ]
    )
    conn = _FakeConn(cursor)

    malicious = (
        '<img src="x" onerror="window.__xss=true">'
        "<script>alert(1)</script>"
        "<h2>Safe</h2>"
        '<a href="javascript:alert(1)">x</a>'
    )
    result = await update_strategy(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-1",
        user_id="u-owner",
        detail_html=malicious,
    )

    # The UPDATE was issued with the sanitized value, not the raw payload.
    expected = normalize_detail_html(malicious)
    # Find the UPDATE execute call (3rd one: assert_owner, UPDATE, …).
    update_call = next(
        (params for sql, params in cursor.executed if "UPDATE" in sql),
        None,
    )
    assert update_call is not None
    assert update_call["detail_html"] == expected
    # Sanity: the dangerous bits really are gone in the sanitized form.
    assert "<script" not in expected.lower()
    assert "onerror" not in expected.lower()
    assert "javascript:" not in expected.lower()
    # Stub returned the post-update detail dict.
    assert result == {
        "id": "strat-1",
        "strategy_code": "STR_FUT_001",
        "detail_html": "<stub>",
        "name": "Stub",
    }


async def test_update_strategy_passes_non_html_fields_verbatim(
    monkeypatch,
) -> None:
    """Non-`detail_html` fields are NOT touched by the sanitizer."""
    monkeypatch.setattr(
        "gr_api.services.strategy.get_strategy_detail",
        _stub_get_strategy_detail,
    )

    cursor = _FakeCursor(
        rows_per_call=[
            {"author_id": "u-owner"},
            {"strategy_code": "STR_FUT_001"},
            None,
            None,
            None,
        ]
    )
    conn = _FakeConn(cursor)

    await update_strategy(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-1",
        user_id="u-owner",
        name="My Renamed Strategy",
        description="<not html, just text>",
    )

    update_call = next(
        (params for sql, params in cursor.executed if "UPDATE" in sql),
        None,
    )
    assert update_call is not None
    assert update_call["name"] == "My Renamed Strategy"
    # description is plain text in the schema; sanitizer not applied to
    # it. We assert the value round-trips untouched.
    assert update_call["description"] == "<not html, just text>"
    # detail_html was NOT included (it's None and the service skips None).
    assert "detail_html" not in update_call


async def test_update_strategy_normalizes_only_detail_html_key(
    monkeypatch,
) -> None:
    """If a future field is added with `_html` suffix, it should still
    be a hard-fail to forget to add the sanitizer — we assert only
    `detail_html` is run through `normalize_detail_html`.
    """
    normalize_calls: list[str] = []

    real_normalize = normalize_detail_html

    def spy_normalize(value: str | None) -> str:
        normalize_calls.append(value or "")
        return real_normalize(value)

    # The service imports `normalize_detail_html` at module top, so the
    # bound name lives at `services.strategy.normalize_detail_html`.
    # Patching the original module's attribute alone wouldn't intercept
    # the service's call.
    monkeypatch.setattr(
        "gr_api.services.strategy.normalize_detail_html",
        spy_normalize,
    )
    monkeypatch.setattr(
        "gr_api.services.strategy.get_strategy_detail",
        _stub_get_strategy_detail,
    )

    cursor = _FakeCursor(
        rows_per_call=[
            {"author_id": "u-owner"},
            {"strategy_code": "STR_FUT_001"},
            None,
            None,
            None,
        ]
    )
    conn = _FakeConn(cursor)

    await update_strategy(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-1",
        user_id="u-owner",
        detail_html="<h2>Hi</h2>",
    )

    # The sanitizer was called exactly once, with the detail_html value.
    assert normalize_calls == ["<h2>Hi</h2>"]


# ---------------------------------------------------------------------------
# IDOR
# ---------------------------------------------------------------------------


async def test_update_strategy_rejects_non_owner(monkeypatch) -> None:
    """A user that is NOT the strategy's author must be rejected with
    Forbidden — even if their payload is well-formed. No UPDATE is
    issued.
    """
    monkeypatch.setattr(
        "gr_api.services.strategy.get_strategy_detail",
        _stub_get_strategy_detail,
    )

    # Only the assert_strategy_owner SELECT runs. author_id="u-owner",
    # but the caller is u-attacker.
    cursor = _FakeCursor(rows_per_call=[{"author_id": "u-owner"}])
    conn = _FakeConn(cursor)

    with pytest.raises(Forbidden):
        await update_strategy(
            conn,  # type: ignore[arg-type]
            strategy_id="strat-1",
            user_id="u-attacker",
            name="Should be rejected",
        )

    # No UPDATE was issued — only the SELECT.
    update_calls = [sql for sql, _ in cursor.executed if "UPDATE" in sql]
    assert update_calls == []


async def test_update_strategy_raises_not_found_for_missing_id(
    monkeypatch,
) -> None:
    """If the strategy doesn't exist, the guard raises NotFound BEFORE
    the UPDATE — not "0 rows updated". Prevents probing field names.
    """
    monkeypatch.setattr(
        "gr_api.services.strategy.get_strategy_detail",
        _stub_get_strategy_detail,
    )

    # assert_strategy_owner returns no row.
    cursor = _FakeCursor(rows_per_call=[None])
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        await update_strategy(
            conn,  # type: ignore[arg-type]
            strategy_id="nonexistent",
            user_id="u-owner",
            name="x",
        )

    update_calls = [sql for sql, _ in cursor.executed if "UPDATE" in sql]
    assert update_calls == []


async def test_update_strategy_allows_owner(monkeypatch) -> None:
    """Sanity: when user_id == author_id, the UPDATE proceeds and the
    post-update detail is returned.
    """
    monkeypatch.setattr(
        "gr_api.services.strategy.get_strategy_detail",
        _stub_get_strategy_detail,
    )

    cursor = _FakeCursor(
        rows_per_call=[
            {"author_id": "u-owner"},
            {"strategy_code": "STR_FUT_001"},
            None,
            None,
            None,
        ]
    )
    conn = _FakeConn(cursor)

    result = await update_strategy(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-1",
        user_id="u-owner",
        name="Owner can rename",
    )

    assert result["name"] == "Stub"  # from the stub
    # UPDATE was issued.
    update_calls = [sql for sql, _ in cursor.executed if "UPDATE" in sql]
    assert len(update_calls) == 1
