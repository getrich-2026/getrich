"""Tests for the signal-settings service.

`services.signal_settings` holds the user's global push preferences
(`get_global_settings` / `update_global_settings`) and per-strategy
overrides (`get_strategy_settings` / `update_strategy_settings`).
"""

from __future__ import annotations

from typing import Any

import pytest

from getrich.apps.web.errors import NotFound
from getrich.apps.web.schemas.subscription import (
    GlobalSettingsIn,
    GlobalSettingsPatch,
    QuietHoursPatch,
    StrategySettingsPatch,
)
from getrich.apps.web.services.signal_settings import (
    get_global_settings,
    get_strategy_settings,
    update_global_settings,
    update_strategy_settings,
)


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Mock async cursor. `set_rows` queues a `fetchall` response,
    `push_one` queues a `fetchone` response (FIFO)."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple | None]] = []
        self._fetchone_q: list[dict[str, Any] | None] = []
        self._fetchall_q: list[list[dict[str, Any]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def execute(self, sql, params=None):
        self.executed.append((sql.strip(), params))

    async def fetchone(self):
        if self._fetchone_q:
            return self._fetchone_q.pop(0)
        return None

    async def fetchall(self):
        if self._fetchall_q:
            return self._fetchall_q.pop(0)
        return []

    def push_one(self, row: dict[str, Any] | None) -> None:
        self._fetchone_q.append(row)

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self._fetchall_q.append(rows)


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.commits: int = 0

    def cursor(self):
        return self._cursor

    async def commit(self) -> None:
        self.commits += 1


# ---------------------------------------------------------------------------
# get_global_settings
# ---------------------------------------------------------------------------


async def test_get_global_settings_returns_defaults_when_uninitialized() -> None:
    """If `user_signal_settings` has no row for the user, the service
    returns the hard-coded defaults without writing them. Only the
    two SELECTs (global + overrides) are issued.
    """
    cursor = _FakeCursor()
    cursor.push_one(None)  # global row absent
    cursor.set_rows([])  # strategy overrides empty
    conn = _FakeConn(cursor)

    result = await get_global_settings(conn, user_id="u-1")  # type: ignore[arg-type]

    assert result["push_enabled"] is True
    assert result["channels"] == {
        "app_push": True,
        "sms": False,
        "email": False,
        "wechat_service": False,
        "websocket": True,
    }
    assert result["global_settings"] == {
        "confidence_threshold": 0.50,
        "urgency_filter": ["normal", "high", "critical"],
        "quiet_hours": {"enabled": False, "start": "22:00", "end": "08:30"},
        "trading_hours_only": False,
    }
    assert result["strategy_overrides"] == []


async def test_get_global_settings_merges_stored_channels_with_defaults() -> None:
    """Stored JSONB that omits a key (e.g. brand-new channel added
    later) must be merged with the defaults so the response has all
    five keys.
    """
    cursor = _FakeCursor()
    cursor.push_one(
        {
            "push_enabled": False,
            "channels": {"app_push": False, "email": True},  # partial
            "confidence_threshold": 0.8,
            "urgency_filter": ["high", "critical"],
            "quiet_hours": {"enabled": True, "start": "23:00", "end": "07:00"},
            "trading_hours_only": True,
        }
    )
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    result = await get_global_settings(conn, user_id="u-1")  # type: ignore[arg-type]

    assert result["push_enabled"] is False
    # The stored keys override defaults; missing keys keep defaults.
    assert result["channels"] == {
        "app_push": False,  # overridden
        "sms": False,  # default
        "email": True,  # overridden
        "wechat_service": False,  # default
        "websocket": True,  # default
    }
    assert result["global_settings"]["confidence_threshold"] == 0.8
    assert result["global_settings"]["urgency_filter"] == ["high", "critical"]
    assert result["global_settings"]["quiet_hours"] == {
        "enabled": True,
        "start": "23:00",
        "end": "07:00",
    }
    assert result["global_settings"]["trading_hours_only"] is True


async def test_get_global_settings_serializes_strategy_overrides() -> None:
    cursor = _FakeCursor()
    cursor.push_one(None)  # no global row
    cursor.set_rows(
        [
            {
                "strategy_code": "STR_FUT_001",
                "push_enabled": False,
                "confidence_threshold": 0.9,
                "notify_entry_only": True,
            },
            {
                "strategy_code": "STR_FUT_002",
                "push_enabled": True,
                "confidence_threshold": None,  # inherit global
                "notify_entry_only": False,
            },
        ]
    )
    conn = _FakeConn(cursor)

    result = await get_global_settings(conn, user_id="u-1")  # type: ignore[arg-type]

    assert result["strategy_overrides"] == [
        {
            "strategy_id": "STR_FUT_001",
            "push_enabled": False,
            "confidence_threshold": 0.9,
            "notify_entry_only": True,
        },
        {
            "strategy_id": "STR_FUT_002",
            "push_enabled": True,
            "confidence_threshold": None,
            "notify_entry_only": False,
        },
    ]


# ---------------------------------------------------------------------------
# update_global_settings
# ---------------------------------------------------------------------------


async def test_update_global_settings_creates_initial_row() -> None:
    """First-time update: get_global_settings returns defaults, so the
    UPSERT is built from defaults + body. The body sets one new
    channel; the result commits.
    """
    cursor = _FakeCursor()
    cursor.push_one(None)  # get_global_settings → no row
    cursor.set_rows([])  # overrides empty
    conn = _FakeConn(cursor)

    result = await update_global_settings(
        conn,  # type: ignore[arg-type]
        user_id="u-1",
        body=GlobalSettingsIn(push_enabled=False),
    )

    assert result == {"updated": True}
    # Last SQL is the INSERT ... ON CONFLICT DO UPDATE.
    last_sql, last_params = cursor.executed[-1]
    assert "INSERT INTO user_signal_settings" in last_sql
    assert "ON CONFLICT (user_id) DO UPDATE" in last_sql
    assert last_params[0] == "u-1"  # user_id
    assert last_params[1] is False  # push_enabled
    # channels serialized as JSON string.
    assert isinstance(last_params[2], str)
    assert conn.commits == 1


async def test_update_global_settings_merges_partial_channels() -> None:
    """If the body sets only `channels.sms = True`, the response
    channels keep the user's stored values for the other channels.
    """
    cursor = _FakeCursor()
    cursor.push_one(
        {
            "push_enabled": True,
            "channels": {
                "app_push": False,
                "sms": False,
                "email": True,
                "wechat_service": False,
                "websocket": True,
            },
            "confidence_threshold": 0.7,
            "urgency_filter": ["high"],
            "quiet_hours": {"enabled": False, "start": "22:00", "end": "08:30"},
            "trading_hours_only": False,
        }
    )
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    body = GlobalSettingsIn(
        channels={"sms": True, "email": False, "wechat_service": True},
    )
    await update_global_settings(
        conn,
        user_id="u-1",
        body=body,  # type: ignore[arg-type]
    )

    last_params = cursor.executed[-1][1]
    import json

    stored_channels = json.loads(last_params[2])
    assert stored_channels == {
        "app_push": False,  # inherited from existing
        "sms": True,  # new
        "email": False,  # new
        "wechat_service": True,  # new
        "websocket": True,  # inherited
    }


async def test_update_global_settings_applies_global_settings_block() -> None:
    """Body fields under `global_settings` (threshold / urgency /
    trading_hours_only / quiet_hours) override the existing values.
    """
    cursor = _FakeCursor()
    cursor.push_one(
        {
            "push_enabled": True,
            "channels": {
                "app_push": True,
                "sms": False,
                "email": False,
                "wechat_service": False,
                "websocket": True,
            },
            "confidence_threshold": 0.5,
            "urgency_filter": ["normal", "high", "critical"],
            "quiet_hours": {"enabled": False, "start": "22:00", "end": "08:30"},
            "trading_hours_only": False,
        }
    )
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    body = GlobalSettingsIn(
        global_settings=GlobalSettingsPatch(
            confidence_threshold=0.9,
            urgency_filter=["critical"],
            trading_hours_only=True,
            quiet_hours=QuietHoursPatch(enabled=True, start="23:30", end="07:00"),
        )
    )
    await update_global_settings(
        conn,
        user_id="u-1",
        body=body,  # type: ignore[arg-type]
    )

    last_params = cursor.executed[-1][1]
    assert last_params[3] == 0.9  # confidence_threshold
    assert last_params[4] == ["critical"]  # urgency_filter
    assert last_params[6] is True  # trading_hours_only
    import json

    quiet = json.loads(last_params[5])
    assert quiet == {
        "enabled": True,
        "start": "23:30",
        "end": "07:00",
    }


# ---------------------------------------------------------------------------
# get_strategy_settings
# ---------------------------------------------------------------------------


async def test_get_strategy_settings_raises_not_found_for_missing_strategy() -> None:
    cursor = _FakeCursor()
    cursor.push_one(None)  # strategy not found
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        await get_strategy_settings(
            conn,  # type: ignore[arg-type]
            user_id="u-1",
            strategy_code="NOPE",
        )


async def test_get_strategy_settings_inherits_global_when_no_override() -> None:
    """With no per-strategy row, the response mirrors the user's
    global settings. Channels and urgency are inherited; the
    per-strategy `enabled` flag defaults to True and
    `notify_entry_only` to False.
    """
    cursor = _FakeCursor()
    cursor.push_one({"id": "strat-uuid-1"})  # strategy exists
    cursor.push_one(None)  # no per-strategy override
    cursor.push_one(None)  # no global row → defaults
    conn = _FakeConn(cursor)

    result = await get_strategy_settings(
        conn,  # type: ignore[arg-type]
        user_id="u-1",
        strategy_code="STR_FUT_001",
    )

    assert result == {
        "strategy_id": "STR_FUT_001",
        "enabled": True,
        "channels": {
            "app_push": True,
            "sms": False,
            "email": False,
            "wechat_service": False,
            "websocket": True,
        },
        "urgency_filter": ["normal", "high", "critical"],
        "confidence_threshold": 0.50,
        "notify_entry_only": False,
    }


async def test_get_strategy_settings_uses_overrides_when_set() -> None:
    """If a per-strategy row exists, the response uses the override
    for `enabled` / `notify_entry_only` / `confidence_threshold` and
    inherits channels/urgency from the global row.
    """
    cursor = _FakeCursor()
    cursor.push_one({"id": "strat-uuid-1"})
    cursor.push_one(
        {
            "push_enabled": False,
            "confidence_threshold": 0.95,
            "notify_entry_only": True,
        }
    )
    cursor.push_one(
        {
            "channels": {
                "app_push": True,
                "sms": True,
                "email": False,
                "wechat_service": False,
                "websocket": True,
            },
            "urgency_filter": ["critical"],
            "confidence_threshold": 0.5,
        }
    )
    conn = _FakeConn(cursor)

    result = await get_strategy_settings(
        conn,  # type: ignore[arg-type]
        user_id="u-1",
        strategy_code="STR_FUT_001",
    )

    assert result["enabled"] is False
    assert result["notify_entry_only"] is True
    # Threshold: override wins over global.
    assert result["confidence_threshold"] == 0.95
    # Channels + urgency filter: inherited from global.
    assert result["channels"] == {
        "app_push": True,
        "sms": True,
        "email": False,
        "wechat_service": False,
        "websocket": True,
    }
    assert result["urgency_filter"] == ["critical"]


async def test_get_strategy_settings_uses_global_threshold_when_override_null() -> None:
    """`confidence_threshold IS NULL` in the override row → fall back
    to the global threshold.
    """
    cursor = _FakeCursor()
    cursor.push_one({"id": "strat-uuid-1"})
    cursor.push_one(
        {
            "push_enabled": True,
            "confidence_threshold": None,
            "notify_entry_only": False,
        }
    )
    cursor.push_one(
        {
            "channels": {
                "app_push": True,
                "sms": False,
                "email": False,
                "wechat_service": False,
                "websocket": True,
            },
            "urgency_filter": ["high"],
            "confidence_threshold": 0.7,
        }
    )
    conn = _FakeConn(cursor)

    result = await get_strategy_settings(
        conn,  # type: ignore[arg-type]
        user_id="u-1",
        strategy_code="STR_FUT_001",
    )

    assert result["confidence_threshold"] == 0.7


# ---------------------------------------------------------------------------
# update_strategy_settings
# ---------------------------------------------------------------------------


async def test_update_strategy_settings_raises_not_found_for_missing_strategy() -> None:
    cursor = _FakeCursor()
    cursor.push_one(None)  # strategy not found
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        await update_strategy_settings(
            conn,  # type: ignore[arg-type]
            user_id="u-1",
            strategy_code="NOPE",
            body=StrategySettingsPatch(enabled=False),
        )


async def test_update_strategy_settings_creates_initial_override() -> None:
    """No prior override → defaults: enabled=True, threshold=None,
    notify_entry_only=False. The body overrides these.
    """
    cursor = _FakeCursor()
    cursor.push_one({"id": "strat-uuid-1"})  # strategy exists
    cursor.push_one(None)  # no prior override
    conn = _FakeConn(cursor)

    result = await update_strategy_settings(
        conn,  # type: ignore[arg-type]
        user_id="u-1",
        strategy_code="STR_FUT_001",
        body=StrategySettingsPatch(
            enabled=False,
            confidence_threshold=0.9,
            notify_entry_only=True,
        ),
    )

    assert result == {"strategy_id": "STR_FUT_001", "updated": True}
    last_sql, last_params = cursor.executed[-1]
    assert "INSERT INTO user_strategy_signal_settings" in last_sql
    assert "ON CONFLICT (user_id, strategy_id) DO UPDATE" in last_sql
    assert last_params == (
        "u-1",
        "strat-uuid-1",
        False,  # push_enabled
        0.9,  # confidence_threshold
        True,  # notify_entry_only
    )
    assert conn.commits == 1


async def test_update_strategy_settings_merges_with_existing_override() -> None:
    """With an existing override, omitted body fields keep their
    prior values; supplied fields replace them.
    """
    cursor = _FakeCursor()
    cursor.push_one({"id": "strat-uuid-1"})
    cursor.push_one(
        {
            "push_enabled": True,
            "confidence_threshold": 0.7,
            "notify_entry_only": False,
        }
    )
    conn = _FakeConn(cursor)

    # Body only sets `enabled` — threshold/notify_entry_only should
    # be inherited from the existing override.
    await update_strategy_settings(
        conn,  # type: ignore[arg-type]
        user_id="u-1",
        strategy_code="STR_FUT_001",
        body=StrategySettingsPatch(enabled=False),
    )

    last_params = cursor.executed[-1][1]
    assert last_params[2] is False  # push_enabled: new
    assert last_params[3] == 0.7  # confidence_threshold: existing
    assert last_params[4] is False  # notify_entry_only: existing
