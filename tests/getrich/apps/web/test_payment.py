"""Tests for the payment service.

`services.payment` is the only inbound path from payment providers
into the orders/subscriptions tables. The two functions are
orthogonal:

- `verify_signature`: synchronous HMAC-SHA256 check, secret read from
  the `PAYMENT_WEBHOOK_SECRET` env var. Skipped in dev (no secret).
- `handle_webhook`: async state-transition for the order + linked
  subscription. Idempotent on `payment_ref`.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Any

import pytest

from getrich.apps.web.errors import BadRequest, NotFound, Unauthorized
from getrich.apps.web.schemas.subscription import PaymentWebhookIn
from getrich.apps.web.services.payment import handle_webhook, verify_signature


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Mock async cursor. Each `execute` increments a counter; the
    test loads the right number of `fetchone` / `fetchall` results via
    `push_one` / `set_rows` so the production code's call pattern is
    satisfied.

    For `handle_webhook` the production code does (in order):
      SELECT (existing payment_ref)  -> fetchone -> may be None
      SELECT (target order)          -> fetchone -> dict or None
      optional UPDATEs               -> no fetch
      commit                         -> n/a
    Plus a SELECT of order items for the access_grant path. Tests push
    exactly the rows they expect to be consumed.
    """

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


def _body(**overrides: Any) -> PaymentWebhookIn:
    base: dict[str, Any] = {
        "order_id": "ORD_20260501_AAAAAAAA",
        "payment_ref": "PAYREF_1",
        "status": "success",
        "amount": 99.0,
        "payment_source": "wechat",
        "paid_at": datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return PaymentWebhookIn(**base)


# ---------------------------------------------------------------------------
# verify_signature
# ---------------------------------------------------------------------------


def test_verify_signature_skips_when_secret_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In dev mode, the service MUST allow webhooks through — the
    spec explicitly states `PAYMENT_WEBHOOK_SECRET` being unset
    bypasses verification. Otherwise dev/test environments break.
    """
    monkeypatch.delenv("PAYMENT_WEBHOOK_SECRET", raising=False)
    # No exception raised.
    verify_signature(b"{}", signature=None)


def test_verify_signature_rejects_missing_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", "super-secret")
    with pytest.raises(Unauthorized):
        verify_signature(b"{}", signature=None)


def test_verify_signature_rejects_bad_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wrong hex digest → 401. Uses constant-time compare to dodge
    timing attacks.
    """
    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", "super-secret")
    with pytest.raises(Unauthorized):
        verify_signature(b"{}", signature="0" * 64)


def test_verify_signature_accepts_valid_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The service recomputes HMAC-SHA256 over the raw body bytes and
    compares to the provided hex digest. The signature here is what
    the production code computes.
    """
    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", "super-secret")
    body = b'{"order_id":"ORD_1"}'
    expected = hmac.new(b"super-secret", body, hashlib.sha256).hexdigest()
    # No exception raised.
    verify_signature(body, signature=expected)


# ---------------------------------------------------------------------------
# handle_webhook — happy path (success)
# ---------------------------------------------------------------------------


async def test_handle_webhook_success_activates_subscription() -> None:
    """A `success` webhook:
    - Looks up the order by `order_id`
    - Updates the order to `status='paid'`, stamping `payment_ref`,
      `payment_source`, and `paid_at`
    - Activates any `pending_payment` subscription tied to the order
    - Creates/updates PayG `strategy_access_grants` from order_items
    """
    cursor = _FakeCursor()
    cursor.push_one(None)  # existing payment_ref: not bound yet
    cursor.push_one({"id": "order-uuid-1", "status": "pending_payment"})
    conn = _FakeConn(cursor)

    result = await handle_webhook(conn, _body())  # type: ignore[arg-type]

    assert result == {"order_id": "ORD_20260501_AAAAAAAA", "processed": True}
    assert conn.commits == 1
    # Three SQL statements: existing-ref lookup, order lookup, UPDATEs
    # (order, subscription, access_grant). UPDATEs do not consume rows.
    assert len(cursor.executed) >= 3
    update_stmts = [sql for sql, _ in cursor.executed if "UPDATE orders" in sql]
    assert any("SET status = 'paid'" in sql for sql in update_stmts)
    assert any("payment_ref = %s" in sql for sql in update_stmts)
    sub_stmts = [sql for sql, _ in cursor.executed if "user_strategy_subscriptions" in sql]
    assert any("status = 'active'" in sql for sql in sub_stmts)
    grant_stmts = [sql for sql, _ in cursor.executed if "strategy_access_grants" in sql]
    assert len(grant_stmts) == 1
    assert "ON CONFLICT (user_id, strategy_id) DO UPDATE" in grant_stmts[0]


# ---------------------------------------------------------------------------
# handle_webhook — order / payment_ref guards
# ---------------------------------------------------------------------------


async def test_handle_webhook_raises_not_found_for_missing_order() -> None:
    cursor = _FakeCursor()
    cursor.push_one(None)  # existing payment_ref: not bound
    cursor.push_one(None)  # order lookup: missing
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        await handle_webhook(conn, _body(order_id="MISSING"))  # type: ignore[arg-type]

    # No UPDATEs and no commit before the raise.
    assert conn.commits == 0


async def test_handle_webhook_rejects_payment_ref_bound_to_other_order() -> None:
    """If `payment_ref` was already used on a different order, the
    webhook is rejected. This is critical for double-payment
    detection.
    """
    cursor = _FakeCursor()
    cursor.push_one({"id": "order-uuid-OTHER", "status": "paid"})
    cursor.push_one({"id": "order-uuid-1", "status": "pending_payment"})
    conn = _FakeConn(cursor)

    with pytest.raises(BadRequest):
        await handle_webhook(conn, _body())  # type: ignore[arg-type]

    assert conn.commits == 0


async def test_handle_webhook_idempotent_for_already_paid_order() -> None:
    """A repeat webhook for a `paid` order returns `processed=True`
    without re-running UPDATEs. The state machine explicitly
    short-circuits for `paid/refunded/cancelled/failed`.
    """
    cursor = _FakeCursor()
    cursor.push_one({"id": "order-uuid-1", "status": "paid"})
    cursor.push_one({"id": "order-uuid-1", "status": "paid"})
    conn = _FakeConn(cursor)

    result = await handle_webhook(conn, _body())  # type: ignore[arg-type]

    assert result == {"order_id": "ORD_20260501_AAAAAAAA", "processed": True}
    # Only the two SELECTs ran; no UPDATE, no commit (we just return).
    update_count = sum(1 for sql, _ in cursor.executed if "UPDATE" in sql)
    assert update_count == 0
    assert conn.commits == 0


async def test_handle_webhook_idempotent_for_already_refunded_order() -> None:
    cursor = _FakeCursor()
    cursor.push_one({"id": "order-uuid-1", "status": "refunded"})
    cursor.push_one({"id": "order-uuid-1", "status": "refunded"})
    conn = _FakeConn(cursor)

    result = await handle_webhook(conn, _body(status="success"))  # type: ignore[arg-type]

    assert result["processed"] is True
    # No state change.
    assert conn.commits == 0


async def test_handle_webhook_payment_ref_self_match_succeeds() -> None:
    """If the same order_id was previously bound to the same payment_ref
    (a normal retry), the `existing.id != order.id` check is False and
    we proceed normally — the success path is allowed to re-run.
    """
    cursor = _FakeCursor()
    cursor.push_one({"id": "order-uuid-1", "status": "paid"})
    cursor.push_one({"id": "order-uuid-1", "status": "pending_payment"})
    conn = _FakeConn(cursor)

    result = await handle_webhook(conn, _body())  # type: ignore[arg-type]

    # It went through the success path. The first two statements are
    # the SELECTs; subsequent are UPDATEs.
    update_stmts = [sql for sql, _ in cursor.executed if "UPDATE" in sql]
    assert any("SET status = 'paid'" in sql for sql in update_stmts)
    assert conn.commits == 1
    assert result["processed"] is True


# ---------------------------------------------------------------------------
# handle_webhook — failed / refunded branches
# ---------------------------------------------------------------------------


async def test_handle_webhook_failed_marks_order_failed() -> None:
    cursor = _FakeCursor()
    cursor.push_one(None)  # existing payment_ref
    cursor.push_one({"id": "order-uuid-1", "status": "pending_payment"})
    conn = _FakeConn(cursor)

    await handle_webhook(conn, _body(status="failed"))  # type: ignore[arg-type]

    update_stmts = [sql for sql, _ in cursor.executed if "UPDATE" in sql]
    assert any("SET status = 'failed'" in sql for sql in update_stmts)
    # No subscription activation on failure.
    sub_stmts = [sql for sql, _ in cursor.executed if "user_strategy_subscriptions" in sql]
    assert sub_stmts == []
    assert conn.commits == 1


async def test_handle_webhook_refunded_cancels_subscription() -> None:
    """A `refunded` webhook cancels any subscription tied to the order
    (regardless of prior status), and stamps `refunded_at` on the
    order. The order must be in a non-terminal state for the
    refunded path to run (a `paid` order would short-circuit as
    already-processed).
    """
    cursor = _FakeCursor()
    cursor.push_one(None)  # existing payment_ref
    cursor.push_one({"id": "order-uuid-1", "status": "processing"})
    conn = _FakeConn(cursor)

    await handle_webhook(conn, _body(status="refunded"))  # type: ignore[arg-type]

    update_stmts = [sql for sql, _ in cursor.executed if "UPDATE" in sql]
    assert any("SET status = 'refunded'" in sql for sql in update_stmts)
    assert any("refunded_at = NOW()" in sql for sql in update_stmts)
    sub_stmts = [sql for sql, _ in cursor.executed if "user_strategy_subscriptions" in sql]
    assert any("status = 'cancelled'" in sql for sql in sub_stmts)
    assert conn.commits == 1
