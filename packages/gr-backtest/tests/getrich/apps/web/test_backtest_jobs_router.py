"""Unit tests for the three ``POST /backtest-jobs/*`` execution endpoints.

Each endpoint should:

* call ``job_svc.create_*_job`` with the right ``job_type`` and the
  caller's ``user_id``,
* dispatch to the matching Celery task via ``app.send_task`` when
  ``Settings.worker.backend == "celery"``,
* fall back to ``background.add_task(run_job_synchronously, ...)`` when
  the backend is ``"inproc"`` (default).

We exercise the route functions directly (no HTTP layer / TestClient)
because the project does not depend on ``httpx`` in its dev extras —
the actual HTTP plumbing is the same as every other FastAPI route and
is tested implicitly by the SSE / artifact-download HTTP tests, which
are already in the suite. Here we care about the **dispatch logic**:
that the three POST handlers wire ``_enqueue`` to the right task name.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import BackgroundTasks

from getrich.apps.web.services import backtest_job as job_svc


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------- fixtures


def _backtest_body() -> dict[str, Any]:
    return {
        "strategy_name": "demo",
        "symbols": ["000001.SZ"],
        "start": "2024-01-01T00:00:00",
        "end": "2024-01-31T00:00:00",
        "initial_cash": "100000",
    }


def _sweep_body() -> dict[str, Any]:
    return {
        "strategy_name": "demo",
        "symbols": ["000001.SZ"],
        "start": "2024-01-01T00:00:00",
        "end": "2024-01-31T00:00:00",
        "initial_cash": "100000",
        "search_spec": {"space": {"lookback": [5, 10, 20]}},
    }


def _walk_forward_body() -> dict[str, Any]:
    return {
        "strategy_name": "demo",
        "symbols": ["000001.SZ"],
        "start": "2024-01-01T00:00:00",
        "end": "2024-12-31T00:00:00",
        "initial_cash": "100000",
        "search_spec": {"space": {"lookback": [5, 10]}},
        "train_months": 6,
        "val_months": 1,
    }


def _make_settings(backend: str) -> MagicMock:
    """Build a settings-like mock with the given worker backend.

    The real ``Settings`` is a frozen dataclass — monkeypatching its
    attributes on teardown raises ``FrozenInstanceError``. The router
    only reads ``settings.worker.backend`` and ``settings.worker.*``,
    so a thin mock with the same surface is sufficient.
    """
    settings = MagicMock()
    settings.worker.backend = backend
    return settings


@pytest.fixture
def _store(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch ``PgBacktestJobStore`` methods used during POST.

    Returns a dict the test can read to assert the right ``job_type`` /
    payload reached the store. ``monkeypatch`` tears down the patch
    after the test.
    """
    calls: dict[str, Any] = {"created": []}
    created_ids = iter([f"job-{i}" for i in range(1, 100)])

    async def fake_create_job(
        *,
        job_type: str,
        ref_id: str,
        request_json: dict[str, Any],
        request_hash: str,
        max_attempts: int,
        user_id: str | None,
        retry_base_seconds: float | None = None,
        retry_cap_seconds: float | None = None,
        retry_jitter_pct: float | None = None,
        conn: Any = None,
    ) -> str:
        calls["created"].append(
            {
                "job_type": job_type,
                "ref_id": ref_id,
                "request_json": request_json,
                "request_hash": request_hash,
                "user_id": user_id,
            }
        )
        return next(created_ids)

    async def fake_get_by_idempotency_key(*, key: str, user_id: str | None, conn: Any = None):
        return None

    monkeypatch.setattr(job_svc._STORE, "create_job", fake_create_job)
    monkeypatch.setattr(job_svc._STORE, "get_by_idempotency_key", fake_get_by_idempotency_key)
    return calls


# ---------------------------------------------------------------- inproc backend


@pytest.fixture
def _inproc_backend(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Force ``GETRICH_WORKER_BACKEND=inproc`` and capture add_task calls."""
    from getrich.apps.web.routers import backtest_jobs as router_mod

    monkeypatch.setattr(router_mod, "settings", _make_settings("inproc"))

    captured: dict[str, Any] = {"calls": []}

    def fake_add(self: Any, func: Any, *args: Any, **kwargs: Any) -> None:
        captured["calls"].append((func.__name__, args, kwargs))

    monkeypatch.setattr(BackgroundTasks, "add_task", fake_add)
    return captured


# ---------------------------------------------------------------- celery backend


@pytest.fixture
def _celery_backend(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Force ``GETRICH_WORKER_BACKEND=celery`` and replace the Celery app."""
    from getrich.apps.web.routers import backtest_jobs as router_mod
    from getrich.apps.worker import celery_app as celery_mod

    monkeypatch.setattr(router_mod, "settings", _make_settings("celery"))
    fake_app = MagicMock()
    fake_app.send_task = MagicMock()
    monkeypatch.setattr(celery_mod, "app", fake_app)
    return fake_app


# ---------------------------------------------------------------- inproc tests


async def test_post_backtest_inproc_enqueues_background_task(
    _store: dict[str, Any], _inproc_backend: dict[str, Any]
) -> None:
    """Default backend (inproc) appends ``run_job_synchronously`` to BackgroundTasks."""
    from getrich.apps.web.routers.backtest_jobs import run_backtest
    from getrich.apps.web.schemas.backtest import BacktestRunRequest

    body = BacktestRunRequest.model_validate(_backtest_body())
    response = await run_backtest(
        body=body,
        background=BackgroundTasks(),
        user_id="user-1",
        db=None,
        idempotency_key=None,
        rid="rid-1",
    )
    assert response["code"] == 0
    payload = response["data"]
    assert payload["status"] == "queued"
    assert payload["job_id"] == "job-1"
    # ``ref_id`` is auto-generated by the service when the request
    # does not provide one — assert it is a 32-char hex (uuid4().hex)
    # rather than a hard-coded sentinel.
    assert isinstance(payload["ref_id"], str) and len(payload["ref_id"]) == 32
    # Store saw a backtest row owned by user-1.
    assert len(_store["created"]) == 1
    assert _store["created"][0]["job_type"] == "backtest"
    assert _store["created"][0]["user_id"] == "user-1"
    # BackgroundTasks was called with the new job_id.
    assert _inproc_backend["calls"] == [("run_job_synchronously", ("job-1",), {})]


async def test_post_sweep_inproc_enqueues_background_task(
    _store: dict[str, Any], _inproc_backend: dict[str, Any]
) -> None:
    """Sweep POST routes to the sweep job_type."""
    from getrich.apps.web.routers.backtest_jobs import run_sweep
    from getrich.apps.web.schemas.backtest import SweepRunRequest

    body = SweepRunRequest.model_validate(_sweep_body())
    response = await run_sweep(
        body=body,
        background=BackgroundTasks(),
        user_id="user-1",
        db=None,
        idempotency_key=None,
        rid="rid-1",
    )
    assert response["code"] == 0
    assert _store["created"][0]["job_type"] == "sweep"
    assert _inproc_backend["calls"] == [("run_job_synchronously", ("job-1",), {})]


async def test_post_walk_forward_inproc_enqueues_background_task(
    _store: dict[str, Any], _inproc_backend: dict[str, Any]
) -> None:
    """Walk-forward POST routes to the walk_forward job_type."""
    from getrich.apps.web.routers.backtest_jobs import run_walk_forward
    from getrich.apps.web.schemas.backtest import WalkForwardRunRequest

    body = WalkForwardRunRequest.model_validate(_walk_forward_body())
    response = await run_walk_forward(
        body=body,
        background=BackgroundTasks(),
        user_id="user-1",
        db=None,
        idempotency_key=None,
        rid="rid-1",
    )
    assert response["code"] == 0
    assert _store["created"][0]["job_type"] == "walk_forward"
    assert _inproc_backend["calls"] == [("run_job_synchronously", ("job-1",), {})]


# ---------------------------------------------------------------- celery tests


async def test_post_backtest_celery_dispatches_backtest_run_job(
    _store: dict[str, Any], _celery_backend: MagicMock
) -> None:
    """Celery backend pushes ``backtest.run_job`` with the new job_id."""
    from getrich.apps.web.routers.backtest_jobs import run_backtest
    from getrich.apps.web.schemas.backtest import BacktestRunRequest

    body = BacktestRunRequest.model_validate(_backtest_body())
    response = await run_backtest(
        body=body,
        background=BackgroundTasks(),
        user_id="user-1",
        db=None,
        idempotency_key=None,
        rid="rid-1",
    )
    assert response["code"] == 0
    _celery_backend.send_task.assert_called_once_with("backtest.run_job", args=["job-1"])


async def test_post_sweep_celery_dispatches_sweep_run_job(
    _store: dict[str, Any], _celery_backend: MagicMock
) -> None:
    """Sweep POST pushes ``sweep.run_job`` (not walk_forward.run_job)."""
    from getrich.apps.web.routers.backtest_jobs import run_sweep
    from getrich.apps.web.schemas.backtest import SweepRunRequest

    body = SweepRunRequest.model_validate(_sweep_body())
    await run_sweep(
        body=body,
        background=BackgroundTasks(),
        user_id="user-1",
        db=None,
        idempotency_key=None,
        rid="rid-1",
    )
    _celery_backend.send_task.assert_called_once_with("sweep.run_job", args=["job-1"])


async def test_post_walk_forward_celery_dispatches_walk_forward_run_job(
    _store: dict[str, Any], _celery_backend: MagicMock
) -> None:
    """Walk-forward POST pushes ``walk_forward.run_job`` (not sweep.run_job)."""
    from getrich.apps.web.routers.backtest_jobs import run_walk_forward
    from getrich.apps.web.schemas.backtest import WalkForwardRunRequest

    body = WalkForwardRunRequest.model_validate(_walk_forward_body())
    await run_walk_forward(
        body=body,
        background=BackgroundTasks(),
        user_id="user-1",
        db=None,
        idempotency_key=None,
        rid="rid-1",
    )
    _celery_backend.send_task.assert_called_once_with("walk_forward.run_job", args=["job-1"])


# ---------------------------------------------------------------- idempotency


async def test_post_backtest_idempotency_key_replays(
    _store: dict[str, Any], _inproc_backend: dict[str, Any]
) -> None:
    """Idempotency-keyed POST that hits an existing row short-circuits to 202 with the stored id."""
    from getrich.apps.web.routers.backtest_jobs import run_backtest
    from getrich.apps.web.schemas.backtest import BacktestRunRequest

    existing = {
        "job_id": "existing-job",
        "ref_id": "existing-ref",
        "request_hash": "",
    }

    async def fake_get_by_idempotency_key(*, key: str, user_id: str | None, conn: Any = None):
        return existing

    job_svc._STORE.get_by_idempotency_key = fake_get_by_idempotency_key  # type: ignore[assignment]
    create_mock = MagicMock()
    job_svc._STORE.create_job = create_mock  # type: ignore[assignment]

    body = BacktestRunRequest.model_validate(_backtest_body())
    response = await run_backtest(
        body=body,
        background=BackgroundTasks(),
        user_id="user-1",
        db=None,
        idempotency_key="key-1",
        rid="rid-1",
    )
    assert response["code"] == 0
    payload = response["data"]
    assert payload["job_id"] == "existing-job"
    assert payload["ref_id"] == "existing-ref"
    # No new row was created.
    create_mock.assert_not_called()
    # BackgroundTasks still enqueued the existing job_id (the operator
    # may want to re-run, but for the inproc path we mirror what the
    # service returned: the existing job_id).
    assert _inproc_backend["calls"] == [("run_job_synchronously", ("existing-job",), {})]
