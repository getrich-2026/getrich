"""Integration tests for ``sync_is_cancelled_status``.

The helper opens a short-lived sync psycopg connection and runs a single
``SELECT status`` against ``backtest_jobs``. It is the per-trial cancel probe
the worker thread uses when the runner lives in a separate process from the
API that issued ``POST /backtest-jobs/{id}/cancel``.

These tests require a real PostgreSQL (the CI test job already provisions
one). They are skipped if ``GETRICH_TEST_PG`` is not set, matching the
existing pattern in ``test_job_persistence.py``.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from getrich_backtest.job_persistence import PgBacktestJobStore, sync_is_cancelled_status


# Only run when the dev / CI Postgres is reachable.
pytestmark = pytest.mark.skipif(
    os.environ.get("GETRICH_TEST_PG") is None
    and not os.path.exists(os.path.expanduser("~/.getrich/test_pg_available")),
    reason="requires real PostgreSQL; set GETRICH_TEST_PG=1 to enable",
)


def _conninfo() -> str:
    """Build a libpq DSN from env vars (CI matches)."""
    user = os.environ.get("PG_USER", "quant")
    password = os.environ.get("PG_PASSWORD", "testpass")
    host = os.environ.get("PG_HOST", "localhost")
    port = os.environ.get("PG_PORT", "5432")
    database = os.environ.get("PG_DB", "getrich")
    pw = f":{password}" if password else ""
    return f"postgresql://{user}{pw}@{host}:{port}/{database}"


@pytest.fixture
async def _seeded_job() -> dict[str, Any]:
    """Insert one backtest_jobs row and return its identifying dict.

    Cleanup is best-effort: a SQL DELETE with the unique ``job_id`` is run
    after the test (the schema uses ``job_id TEXT PRIMARY KEY`` so we
    don't need to know the user_id at teardown time).
    """
    import psycopg

    store = PgBacktestJobStore()
    payload = {"strategy_name": "demo", "symbols": ["000001.SZ"]}
    job_id = await store.create_job(
        job_type="backtest",
        ref_id="ref-sync-probe",
        request_json=payload,
        request_hash="h" * 64,
        max_attempts=1,
        user_id="*",
    )
    yield {"job_id": job_id, "ref_id": "ref-sync-probe"}
    # Best-effort cleanup
    try:
        with psycopg.connect(_conninfo(), autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM backtest.backtest_jobs WHERE job_id = %s", (job_id,))
    except Exception:  # noqa: BLE001
        pass


async def test_sync_probe_returns_false_for_queued_status(_seeded_job: dict[str, Any]) -> None:
    """A freshly-created row is in 'queued' → probe returns False."""
    assert sync_is_cancelled_status(_seeded_job["job_id"], conninfo=_conninfo()) is False


async def test_sync_probe_returns_true_after_mark_cancelled(_seeded_job: dict[str, Any]) -> None:
    """After ``mark_cancelled``, the probe returns True."""
    store = PgBacktestJobStore()
    await store.mark_cancelled(_seeded_job["job_id"], user_id="*")
    assert sync_is_cancelled_status(_seeded_job["job_id"], conninfo=_conninfo()) is True


async def test_sync_probe_returns_false_for_missing_job_id() -> None:
    """A non-existent job_id returns False (not an exception)."""
    assert sync_is_cancelled_status("nonexistent-job-id", conninfo=_conninfo()) is False


def test_sync_probe_returns_false_on_db_error() -> None:
    """A bad DSN returns False (fail-open) rather than raising.

    The contract: ``sync_is_cancelled_status`` must never raise — a
    transient DB outage should not abort a healthy job. The runner
    will re-probe on the next trial boundary.
    """
    bad_conninfo = "postgresql://nobody:nopass@127.0.0.1:1/none"
    assert sync_is_cancelled_status("any-job", conninfo=bad_conninfo) is False


def test_sync_probe_raises_runtime_error_when_psycopg_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ``psycopg`` (sync) is not importable, the function raises a clear error.

    We don't actually uninstall psycopg in CI; we simulate by hiding the
    import with a sys.modules shim. The function uses ``import psycopg``
    *inside* the body (lazy import) so the patch must replace it before
    the call.
    """
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "psycopg":
            raise ImportError("simulated missing psycopg")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="psycopg"):
        sync_is_cancelled_status("any", conninfo="postgresql://x")
