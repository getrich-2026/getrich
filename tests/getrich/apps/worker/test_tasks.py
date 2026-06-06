"""Tests for the Celery task bodies.

The task bodies (``run_backtest_job`` / ``run_sweep_job`` /
``run_walk_forward_job``) are thin wrappers that all delegate to
``_run_job_sync``. We exercise that shared helper here, plus the
per-task wrappers, to make sure the ``op`` selection by ``job_type``
is correct and the runner is invoked exactly once per task call.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from getrich.apps.worker import tasks as worker_tasks
from getrich_backtest.job_persistence import PgBacktestJobStore


def _fake_run_result() -> Any:
    out = MagicMock()
    out.to_dict.return_value = {
        "claimed": True,
        "job_id": "job-1",
        "final_status": "completed",
        "error": None,
    }
    return out


class _FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, str]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        # The service builds ``BacktestJobRunner(...)`` then
        # ``asyncio.run(runner.run_once())``. The runner's run_once
        # is async, so we await an async wrapper.
        return _FakeRunner._async_run(self)

    @staticmethod
    async def _async_run(runner_self: _FakeRunner) -> Any:
        return _fake_run_result()


def _row(job_type: str) -> dict[str, Any]:
    return {
        "job_id": "job-1",
        "job_type": job_type,
        "ref_id": f"ref-{job_type}",
        "status": "queued",
        "request_json": "{}",
        "progress": 0,
        "attempt": 1,
        "max_attempts": 1,
    }


@pytest.fixture
def _stub_dependencies(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch the store, runner, and pool so _run_job_sync is hermetic."""
    calls: dict[str, Any] = {"run_once": 0, "ops_seen": []}

    async def fake_get_job(_job_id: str, *, user_id: str | None = None, conn: Any = None) -> Any:
        # Caller passes user_id; we record the last call's job_type
        # by switching on a thread-local-ish dict.
        return _row(calls.get("next_type", "backtest"))

    def fake_init_pg_pool() -> None:
        calls["init"] = calls.get("init", 0) + 1

    def fake_close_pg_pool() -> None:
        calls["close"] = calls.get("close", 0) + 1

    fake_run_result = _fake_run_result()

    def fake_make_runner(
        _store: Any,
        op: Any,
        *,
        job_type: str,
        sleep_seconds: float = 0,
        db_conninfo: str = "",
    ) -> Any:
        calls["ops_seen"].append((job_type, type(op).__name__))

        class _StubRunner:
            async def run_once(self: Any) -> Any:  # noqa: N805
                return fake_run_result

        return _StubRunner()

    monkeypatch.setattr(worker_tasks, "_STORE", MagicMock(spec=PgBacktestJobStore))
    monkeypatch.setattr(worker_tasks._STORE, "get_job", fake_get_job)
    monkeypatch.setattr(worker_tasks, "get_op_for_job_type", lambda jt: f"op-for-{jt}")
    monkeypatch.setattr(worker_tasks, "BacktestJobRunner", fake_make_runner)
    monkeypatch.setattr(worker_tasks, "init_pg_pool", fake_init_pg_pool)
    monkeypatch.setattr(worker_tasks, "close_pg_pool", fake_close_pg_pool)
    return calls


def test_run_backtest_job_picks_backtest_op(_stub_dependencies: dict[str, Any]) -> None:
    _stub_dependencies["next_type"] = "backtest"
    out = worker_tasks.run_backtest_job.apply(args=["job-1"]).get()
    assert out == {
        "claimed": True,
        "job_id": "job-1",
        "final_status": "completed",
        "error": None,
    }
    assert _stub_dependencies["ops_seen"] == [("backtest", "str")]
    assert _stub_dependencies["init"] == 1
    assert _stub_dependencies["close"] == 1


def test_run_sweep_job_picks_sweep_op(_stub_dependencies: dict[str, Any]) -> None:
    _stub_dependencies["next_type"] = "sweep"
    worker_tasks.run_sweep_job.apply(args=["job-1"]).get()
    assert _stub_dependencies["ops_seen"] == [("sweep", "str")]


def test_run_walk_forward_job_picks_walk_forward_op(
    _stub_dependencies: dict[str, Any],
) -> None:
    _stub_dependencies["next_type"] = "walk_forward"
    worker_tasks.run_walk_forward_job.apply(args=["job-1"]).get()
    assert _stub_dependencies["ops_seen"] == [("walk_forward", "str")]


def test_run_job_sync_handles_missing_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the row vanished between POST and consume, return a friendly
    'job not found' result rather than raise."""
    monkeypatch.setattr(worker_tasks, "init_pg_pool", lambda: None)
    monkeypatch.setattr(worker_tasks, "close_pg_pool", lambda: None)
    fake_store = MagicMock()
    fake_store.get_job = MagicMock(
        side_effect=lambda _job_id, *, user_id=None, conn=None: asyncio.sleep(0) or None
    )
    monkeypatch.setattr(worker_tasks, "_STORE", fake_store)
    out = worker_tasks._run_job_sync("vanished")
    assert out == {
        "claimed": False,
        "job_id": "vanished",
        "final_status": None,
        "error": "job not found",
    }
