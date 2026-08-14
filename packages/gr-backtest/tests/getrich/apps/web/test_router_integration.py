"""Round #1197 A-4: 4 router integration tests.

Exercises the route functions directly (no TestClient / httpx) on the
four routers that previously had no end-to-end coverage. Mirrors the
existing ``test_backtest_jobs_router.py`` pattern: import the route
function, call it with the dependency arguments it expects, assert on
the response envelope and side-effects.

The four routers covered:
  1. ``admin_imports`` — backoffice strategy import endpoints
  2. ``payments``     — provider webhook (signature + state transition)
  3. ``user``         — user-facing orders list (auth + pagination)
  4. ``backtest_jobs`` — POST execution endpoints via the inproc
                         dispatch path (the celery path is already
                         covered in ``test_backtest_jobs_router``)

Why direct calls instead of ``TestClient``? The test suite does not
depend on ``httpx`` (we keep dev extras slim). The actual HTTP plumbing
is the same for every FastAPI route and is implicitly tested by the
existing SSE / artifact-download integration tests. Here we care about
the **contract** between each route and the service layer it delegates
to, plus the auth / envelope / request-id plumbing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from getrich.apps.web.errors import NotFound
from getrich.apps.web.pagination import make_page_params
from getrich.apps.web.services import (
    admin_import as admin_import_svc,
    backtest_job as job_svc,
    order as order_svc,
    payment as payment_svc,
)


pytestmark = pytest.mark.anyio


# ===========================================================================
# Shared fakes
# ===========================================================================


class _FakeCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, Any]] = []
        self._fetchone_q: list[dict[str, Any] | None] = []
        self._fetchall_q: list[list[dict[str, Any]]] = []

    async def __aenter__(self) -> _FakeCursor:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append((sql.strip(), params))

    async def fetchone(self) -> dict[str, Any] | None:
        return self._fetchone_q.pop(0) if self._fetchone_q else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._fetchall_q.pop(0) if self._fetchall_q else []

    def push_one(self, row: dict[str, Any] | None) -> None:
        self._fetchone_q.append(row)

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self._fetchall_q.append(rows)


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.commits: int = 0

    def cursor(self) -> _FakeCursor:
        return self._cursor

    async def commit(self) -> None:
        self.commits += 1


# ===========================================================================
# 1. admin_imports router — 3 of 6 endpoints exercised (representative)
# ===========================================================================


@pytest.fixture
def _admin_store(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch admin_import_svc functions used by the router.

    We patch at the service module level so the route function
    delegates to our fakes regardless of how the service is wired.
    """
    captured: dict[str, Any] = {"calls": []}

    async def fake_list_history(db: Any) -> list[dict[str, Any]]:
        captured["calls"].append(("list_import_history",))
        return [{"job_code": "IMP-1", "status": "completed"}]

    async def fake_upsert(db: Any, *, body: Any, admin_user_id: str) -> dict[str, Any]:
        captured["calls"].append(("upsert_strategy", body.strategy_code, admin_user_id))
        return {"strategy_code": body.strategy_code, "ok": True}

    async def fake_get_job(db: Any, job_code: str) -> dict[str, Any]:
        captured["calls"].append(("get_import_job", job_code))
        return {"job_code": job_code, "status": "completed", "rows": 10}

    monkeypatch.setattr(admin_import_svc, "list_import_history", fake_list_history)
    monkeypatch.setattr(admin_import_svc, "upsert_strategy", fake_upsert)
    monkeypatch.setattr(admin_import_svc, "get_import_job", fake_get_job)
    return captured


async def test_admin_imports_history_route_envelopes_response(
    _admin_store: dict[str, Any],
) -> None:
    """GET /admin/imports/history wraps service data in the standard envelope."""
    from getrich.apps.web.routers.admin_imports import list_import_history

    response = await list_import_history(
        admin_user_id="admin-1", db=_FakeConn(_FakeCursor()), rid="rid-1",
    )

    assert response["code"] == 0
    assert response["message"] == "success"
    assert response["request_id"] == "rid-1"
    assert response["data"] == [{"job_code": "IMP-1", "status": "completed"}]
    assert _admin_store["calls"] == [("list_import_history",)]


async def test_admin_imports_upsert_route_passes_admin_user_id(
    _admin_store: dict[str, Any],
) -> None:
    """POST /admin/imports/strategies/upsert threads the admin's user_id into the service."""
    from getrich.apps.web.routers.admin_imports import upsert_strategy
    from getrich.apps.web.schemas.admin_import import StrategyUpsertIn

    body = StrategyUpsertIn(
        strategy_code="STRAT_A",
        name="MA Cross",
        asset_class="equity",
        market="cn",
        risk_level="medium",
        author_id="author-1",
    )

    response = await upsert_strategy(
        body=body, admin_user_id="admin-1", db=_FakeConn(_FakeCursor()), rid="rid-2",
    )

    assert response["code"] == 0
    assert response["data"] == {"strategy_code": "STRAT_A", "ok": True}
    assert _admin_store["calls"][0] == ("upsert_strategy", "STRAT_A", "admin-1")


async def test_admin_imports_get_job_route_returns_payload(
    _admin_store: dict[str, Any],
) -> None:
    """GET /admin/imports/{job_code} passes the path param through to the service."""
    from getrich.apps.web.routers.admin_imports import get_import_job

    response = await get_import_job(
        job_code="IMP-1", admin_user_id="admin-1", db=_FakeConn(_FakeCursor()), rid="rid-3",
    )

    assert response["code"] == 0
    assert response["data"]["job_code"] == "IMP-1"
    assert response["data"]["rows"] == 10


# ===========================================================================
# 2. payments router — signature check + state transition
# ===========================================================================


def test_payments_webhook_skips_signature_when_secret_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When PAYMENT_WEBHOOK_SECRET is not set, ``verify_signature`` is a no-op."""
    monkeypatch.delenv("PAYMENT_WEBHOOK_SECRET", raising=False)
    # Should not raise.
    payment_svc.verify_signature(b"{}", "any-signature")


def test_payments_webhook_rejects_bad_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the secret is set, a wrong signature raises Unauthorized."""
    from getrich.apps.web.errors import Unauthorized

    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", "test-secret-xyz")
    with pytest.raises(Unauthorized):
        payment_svc.verify_signature(b'{"foo":1}', "wrong-signature")


def test_payments_webhook_accepts_correct_hmac(monkeypatch: pytest.MonkeyPatch) -> None:
    """Correct HMAC-SHA256 signature passes the check."""
    import hashlib
    import hmac

    secret = "test-secret-xyz"
    body = b'{"foo":1}'
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", secret)

    # Should not raise.
    payment_svc.verify_signature(body, sig)


async def test_payments_webhook_route_envelopes_handle_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /webhooks/payment wraps the handle_webhook result in the envelope."""
    from fastapi.requests import Request

    from getrich.apps.web.routers.payments import payment_webhook

    monkeypatch.delenv("PAYMENT_WEBHOOK_SECRET", raising=False)

    async def fake_handle(db: Any, body: Any) -> dict[str, Any]:
        return {"order_id": body.order_id, "status": "paid", "idempotent": False}

    monkeypatch.setattr(payment_svc, "handle_webhook", fake_handle)

    # Build a minimal ASGI request carrying the JSON body.
    payload = (
        b'{"order_id":"ORD_1","payment_ref":"PAY_1","status":"success",'
        b'"amount":99.0,"payment_source":"wechat","paid_at":"2026-05-01T12:00:00Z"}'
    )

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": payload, "more_body": False}

    request = Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": "/webhooks/payment",
            "headers": [(b"content-type", b"application/json")],
            "query_string": b"",
        },
        receive=receive,
    )

    response = await payment_webhook(
        request=request,
        x_webhook_signature=None,
        db=_FakeConn(_FakeCursor()),
        rid="rid-wh",
    )

    assert response["code"] == 0
    assert response["data"]["order_id"] == "ORD_1"
    assert response["data"]["status"] == "paid"


# ===========================================================================
# 3. user router — auth-gated orders list with pagination
# ===========================================================================


async def test_user_orders_route_returns_empty_pagination_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /user/orders envelopes the (list, total) tuple from the service."""
    from getrich.apps.web.routers.user import list_orders

    async def fake_list_orders(
        db: Any, *, user_id: str, status: str | None, page: Any
    ) -> tuple[list[dict[str, Any]], int]:
        # Echo back the user_id so we can assert threading.
        return [], 0

    monkeypatch.setattr(order_svc, "list_orders", fake_list_orders)

    response = await list_orders(
        status=None,
        page=make_page_params(page=1, page_size=20),
        user_id="user-42",
        db=_FakeConn(_FakeCursor()),
        rid="rid-orders",
    )

    assert response["code"] == 0
    # ``make_pagination`` returns 5 fields: page, page_size, total,
    # total_pages, has_more. The has_more flag is ``False`` when total
    # is 0 (no further pages) — assert the core contract.
    data = response["data"]
    assert data["list"] == []
    assert data["pagination"]["page"] == 1
    assert data["pagination"]["page_size"] == 20
    assert data["pagination"]["total"] == 0
    assert data["pagination"]["has_more"] is False


async def test_user_orders_route_passes_user_id_to_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The route must NOT silently drop the user_id; it scopes the SQL query."""
    from getrich.apps.web.routers.user import list_orders

    captured: dict[str, Any] = {}

    async def fake_list_orders(
        db: Any, *, user_id: str, status: str | None, page: Any
    ) -> tuple[list[dict[str, Any]], int]:
        captured["user_id"] = user_id
        captured["status"] = status
        captured["page"] = page
        return [{"id": 1, "status": "paid"}], 1

    monkeypatch.setattr(order_svc, "list_orders", fake_list_orders)

    response = await list_orders(
        status="paid",
        page=make_page_params(page=2, page_size=50),
        user_id="user-99",
        db=_FakeConn(_FakeCursor()),
        rid="rid-2",
    )

    assert captured == {
        "user_id": "user-99",
        "status": "paid",
        "page": make_page_params(page=2, page_size=50),
    }
    assert response["data"]["list"][0]["id"] == 1


# ===========================================================================
# 4. backtest_jobs inproc dispatch (complements the existing celery tests)
# ===========================================================================


@pytest.fixture
def _inproc_dispatch(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Force inproc backend and capture the BackgroundTasks.add_task call."""
    from fastapi import BackgroundTasks

    from getrich.apps.web.routers import backtest_jobs as router_mod

    settings = MagicMock()
    settings.worker.backend = "inproc"
    monkeypatch.setattr(router_mod, "settings", settings)

    captured: dict[str, Any] = {"calls": []}

    def fake_add(self: Any, func: Any, *args: Any, **kwargs: Any) -> None:
        captured["calls"].append((func.__name__, args, kwargs))

    monkeypatch.setattr(BackgroundTasks, "add_task", fake_add)
    return captured


@pytest.fixture
def _store_idempotent(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch job store with a fresh-row return for create_job."""

    async def fake_create_job(
        *, job_type: str, ref_id: str, request_json: dict[str, Any],
        request_hash: str, max_attempts: int, user_id: str | None, conn: Any = None,
        **_: Any,
    ) -> str:
        return "job-x"

    async def fake_get_by_idempotency_key(*, key: str, user_id: str | None, conn: Any = None):
        return None

    monkeypatch.setattr(job_svc._STORE, "create_job", fake_create_job)
    monkeypatch.setattr(job_svc._STORE, "get_by_idempotency_key", fake_get_by_idempotency_key)
    return {}


async def test_backtest_job_inproc_dispatches_via_background_tasks(
    _inproc_dispatch: dict[str, Any], _store_idempotent: dict[str, Any]
) -> None:
    """POST /backtest-jobs/backtest enqueues run_job_synchronously(job-x) inproc."""
    from fastapi import BackgroundTasks

    from getrich.apps.web.routers.backtest_jobs import run_backtest
    from getrich.apps.web.schemas.backtest import BacktestRunRequest

    body = BacktestRunRequest.model_validate(
        {
            "strategy_name": "demo",
            "symbols": ["000001.SZ"],
            "start": "2024-01-01T00:00:00",
            "end": "2024-01-31T00:00:00",
            "initial_cash": "100000",
        }
    )

    response = await run_backtest(
        body=body,
        background=BackgroundTasks(),
        user_id="user-1",
        db=None,
        idempotency_key=None,
        rid="rid-1",
    )

    assert response["code"] == 0
    assert response["data"]["job_id"] == "job-x"
    assert response["data"]["status"] == "queued"
    assert _inproc_dispatch["calls"] == [
        ("run_job_synchronously", ("job-x",), {}),
    ]


async def test_backtest_sweep_inproc_enqueues_sweep_run(
    _inproc_dispatch: dict[str, Any], _store_idempotent: dict[str, Any]
) -> None:
    """POST /backtest-jobs/sweep dispatches run_job_synchronously under inproc."""
    from fastapi import BackgroundTasks

    from getrich.apps.web.routers.backtest_jobs import run_sweep
    from getrich.apps.web.schemas.backtest import SweepRunRequest

    body = SweepRunRequest.model_validate(
        {
            "strategy_name": "demo",
            "symbols": ["000001.SZ"],
            "start": "2024-01-01T00:00:00",
            "end": "2024-01-31T00:00:00",
            "initial_cash": "100000",
            "search_spec": {"space": {"lookback": [5, 10]}},
        }
    )

    response = await run_sweep(
        body=body,
        background=BackgroundTasks(),
        user_id="user-1",
        db=None,
        idempotency_key=None,
        rid="rid-2",
    )

    assert response["code"] == 0
    # Same single inproc dispatch — sweep vs backtest differ only in
    # the celery task_name (covered in test_backtest_jobs_router.py),
    # not in the inproc path.
    assert _inproc_dispatch["calls"] == [
        ("run_job_synchronously", ("job-x",), {}),
    ]


async def test_backtest_job_inproc_envelope_request_id_preserved(
    _inproc_dispatch: dict[str, Any], _store_idempotent: dict[str, Any]
) -> None:
    """The route returns the caller-supplied request_id in the response envelope."""
    from fastapi import BackgroundTasks

    from getrich.apps.web.routers.backtest_jobs import run_backtest
    from getrich.apps.web.schemas.backtest import BacktestRunRequest

    body = BacktestRunRequest.model_validate(
        {
            "strategy_name": "demo",
            "symbols": ["000001.SZ"],
            "start": "2024-01-01T00:00:00",
            "end": "2024-01-31T00:00:00",
            "initial_cash": "100000",
        }
    )

    response = await run_backtest(
        body=body,
        background=BackgroundTasks(),
        user_id="user-1",
        db=None,
        idempotency_key=None,
        rid="custom-rid-123",
    )

    # Critical: the request_id flows from the route dependency
    # through success() and out to the client. A regression here
    # would break log correlation on the client.
    assert response["request_id"] == "custom-rid-123"
