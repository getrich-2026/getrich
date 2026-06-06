"""Smoke tests for the Celery app factory.

The Celery app is mostly a thin config wrapper around ``getrich.config.settings``.
These tests assert the three public surfaces:

* The three ``run_job`` tasks are registered under their stable names
  (``backtest.run_job`` / ``sweep.run_job`` / ``walk_forward.run_job``).
* The broker URL is sourced from ``Settings.worker.broker_url``.
* ``task_routes`` groups all three into the default queue.
* The reliability knobs (acks_late, prefetch_multiplier, etc.) are set
  so a worker restart in production does not lose in-flight tasks.
"""

from __future__ import annotations

import pytest

from getrich.apps.worker import celery_app
from getrich.config.settings import settings as app_settings


@pytest.fixture(autouse=True)
def _reload_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # The app module is already imported by the time tests start, so
    # we cannot rely on env-var flips for the broker URL test below.
    # (The Celery app is built once at import time.)
    yield


def test_three_run_job_tasks_registered() -> None:
    """All three task names are present in the Celery app registry."""
    names = {n for n in celery_app.app.tasks if not n.startswith("celery.")}
    assert {"backtest.run_job", "sweep.run_job", "walk_forward.run_job"}.issubset(names)


def test_broker_url_matches_settings() -> None:
    assert celery_app.app.conf.broker_url == app_settings.worker.broker_url


def test_result_backend_matches_settings() -> None:
    assert celery_app.app.conf.result_backend == app_settings.worker.result_backend


def test_acks_late_enabled() -> None:
    """Late ACK is required for at-least-once delivery on worker crash."""
    assert celery_app.app.conf.task_acks_late is True


def test_reject_on_worker_lost() -> None:
    """Pair with acks_late: a vanished worker re-queues the message."""
    assert celery_app.app.conf.task_reject_on_worker_lost is True


def test_prefetch_multiplier_one() -> None:
    """Never prefetch more than one task — backtests are long-running."""
    assert celery_app.app.conf.worker_prefetch_multiplier == 1


def test_routes_default_queue() -> None:
    """All three task names are routed to the default queue today."""
    routes = celery_app.app.conf.task_routes
    assert routes["backtest.run_job"]["queue"] == "default"
    assert routes["sweep.run_job"]["queue"] == "default"
    assert routes["walk_forward.run_job"]["queue"] == "default"


def test_serializer_is_json() -> None:
    """JSON keeps the job_id payload simple (str) and debuggable."""
    assert celery_app.app.conf.task_serializer == "json"
    assert celery_app.app.conf.result_serializer == "json"
    assert "json" in celery_app.app.conf.accept_content
