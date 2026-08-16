"""Tests for the subscription service.

`services.subscription` is a P0 revenue path (paywall gating strategy
detail). The only currently uncovered functions are
`get_subscription_status` and the `_gen_order_no` helper. The
`subscribe` and `unsubscribe` flows are complex multi-cursor
transactions and are exercised by end-to-end manual smoke tests in
the dev DB; we focus on the deterministic, testable surface here.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pytest
from gr_api.errors import NotFound
from gr_api.services.subscription import (
    _gen_order_no,
    get_subscription_status,
)


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Mock async cursor. `fetchone` and `fetchall` are driven by the
    `executed` stack — we record each (sql, params) pair as `execute`
    is called, and the test sets up `respond` to map (sql, params)
    back to a row.

    The simpler approach (return row N for the Nth call) doesn't work
    here because `get_subscription_status` issues 1 or 2 SELECTs
    depending on whether `user_id` is None.
    """

    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, Any] | None]] = []
        self._next_rows: list[dict[str, Any] | None] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def execute(self, sql, params=None):
        self.executed.append((sql.strip(), params))

    async def fetchone(self):
        # Pop from a queue the test pushes into via `push_row`.
        if self._next_rows:
            return self._next_rows.pop(0)
        return None

    async def fetchall(self):
        return []

    def push_row(self, row: dict[str, Any] | None) -> None:
        self._next_rows.append(row)


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self):
        return self._cursor


# ---------------------------------------------------------------------------
# _gen_order_no
# ---------------------------------------------------------------------------


def test_gen_order_no_has_expected_prefix_and_length() -> None:
    """Order numbers are human-scannable: `ORD_YYYYMMDD_XXXXXXXX`
    (8 hex chars, uppercase). Used by the support team when matching
    payment-provider callbacks to internal records; format must NOT drift.
    """
    fixed = datetime(2026, 5, 1, 12, 30, 0)
    no = _gen_order_no(fixed)
    assert no.startswith("ORD_20260501_")
    assert len(no) == len("ORD_20260501_") + 8
    suffix = no.removeprefix("ORD_20260501_")
    assert len(suffix) == 8
    assert suffix == suffix.upper()
    # Hex check: all chars are 0-9 / A-F.
    int(suffix, 16)


def test_gen_order_no_is_unique_across_calls() -> None:
    """`secrets.token_hex(4)` gives 8 hex chars from a 32-bit CSPRNG.
    Two calls in the same second must still differ — otherwise the
    order_no is not actually unique, which breaks payment reconciliation.
    """
    fixed = datetime(2026, 5, 1, 12, 30, 0)
    a = _gen_order_no(fixed)
    b = _gen_order_no(fixed)
    assert a != b


# ---------------------------------------------------------------------------
# get_subscription_status
# ---------------------------------------------------------------------------


async def test_get_status_returns_is_subscribed_false_when_anonymous() -> None:
    """An anonymous viewer (user_id=None) gets the strategy's pricing
    but `is_subscribed=False` and no subscription fields. No
    subscription-row SELECT is issued.
    """
    cursor = _FakeCursor()
    cursor.push_row(
        {
            "id": "strat-1",
            "subscription_monthly": 99,
            "subscription_yearly": 999,
        }
    )
    conn = _FakeConn(cursor)

    result = await get_subscription_status(
        conn,  # type: ignore[arg-type]
        user_id=None,
        strategy_code="STR_FUT_001",
    )

    assert result["is_subscribed"] is False
    assert result["subscription_id"] is None
    assert result["status"] is None
    assert result["plan_type"] is None
    assert result["start_date"] is None
    assert result["expire_date"] is None
    assert result["auto_renew"] is None
    assert result["subscription_price"] == {"monthly": 99.0, "yearly": 999.0}
    # Only the strategy SELECT was issued.
    assert len(cursor.executed) == 1


async def test_get_status_returns_active_when_subscription_alive() -> None:
    """If a row exists with status='active' AND expire_date >= today,
    the response shows is_subscribed=True with all fields populated.
    """
    cursor = _FakeCursor()
    cursor.push_row(
        {
            "id": "strat-1",
            "subscription_monthly": 99,
            "subscription_yearly": 999,
        }
    )
    cursor.push_row(
        {
            "id": "sub-001",
            "plan_type": "monthly",
            "status": "active",
            "start_date": date(2026, 5, 1),
            "expire_date": date(2027, 6, 1),  # one year out
            "auto_renew": True,
        }
    )
    conn = _FakeConn(cursor)

    result = await get_subscription_status(
        conn,  # type: ignore[arg-type]
        user_id="u-1",
        strategy_code="STR_FUT_001",
    )

    assert result["is_subscribed"] is True
    assert result["subscription_id"] == "sub-001"
    assert result["status"] == "active"
    assert result["plan_type"] == "monthly"
    assert result["start_date"] == "2026-05-01"
    assert result["expire_date"] == "2027-06-01"
    assert result["auto_renew"] is True


async def test_get_status_returns_inactive_when_subscription_expired() -> None:
    """An existing subscription whose expire_date is in the past shows
    `is_subscribed=False` even though the row exists — paywall must
    close on expiry.
    """
    cursor = _FakeCursor()
    cursor.push_row(
        {
            "id": "strat-1",
            "subscription_monthly": 99,
            "subscription_yearly": 999,
        }
    )
    cursor.push_row(
        {
            "id": "sub-001",
            "plan_type": "monthly",
            "status": "active",  # status says active but date says expired
            "start_date": date(2024, 1, 1),
            "expire_date": date(2024, 2, 1),  # 2024, way in the past
            "auto_renew": False,
        }
    )
    conn = _FakeConn(cursor)

    result = await get_subscription_status(
        conn,  # type: ignore[arg-type]
        user_id="u-1",
        strategy_code="STR_FUT_001",
    )

    # The row is still surfaced (so the frontend can show "expired"
    # and offer a renewal CTA), but `is_subscribed` is False so the
    # gated content is NOT served.
    assert result["is_subscribed"] is False
    assert result["subscription_id"] == "sub-001"
    assert result["expire_date"] == "2024-02-01"


async def test_get_status_raises_not_found_for_missing_strategy() -> None:
    cursor = _FakeCursor()
    cursor.push_row(None)  # strategy not found
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        await get_subscription_status(
            conn,  # type: ignore[arg-type]
            user_id="u-1",
            strategy_code="NONEXISTENT",
        )
