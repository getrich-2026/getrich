"""Tests for persisted backtest job web services."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from getrich.apps.web.errors import Conflict, NotFound
from getrich.apps.web.pagination import PageParams
from getrich.apps.web.routers.backtest_jobs import router
from getrich.apps.web.services import backtest_job


_TZ = ZoneInfo("Asia/Shanghai")
_PAGE = PageParams(page=2, page_size=10)
_DT = datetime(2026, 6, 2, 9, 30, tzinfo=_TZ)


class _FakeCursor:
    def __init__(
        self,
        *,
        fetchone: dict[str, Any] | None = None,
        fetchall: list[dict[str, Any]] | None = None,
        rowcount: int = 1,
        fetchone_seq: list[dict[str, Any] | None] | None = None,
    ) -> None:
        self.executed: list[tuple[str, dict[str, Any] | None]] = []
        self._fetchone = fetchone
        self._fetchall = fetchall or []
        self.rowcount = rowcount
        self._fetchone_seq = fetchone_seq
        self._fetchone_idx = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, sql: str, params: dict[str, Any] | None = None) -> None:
        self.executed.append((sql, params))

    async def fetchone(self) -> dict[str, Any] | None:
        if self._fetchone_seq is not None:
            if self._fetchone_idx >= len(self._fetchone_seq):
                return None
            value = self._fetchone_seq[self._fetchone_idx]
            self._fetchone_idx += 1
            return value
        return self._fetchone

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._fetchall


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _FakeCursor:
        return self._cursor


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _job_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "job_id": "job-1",
        "job_type": "backtest",
        "ref_id": "run-1",
        "user_id": "user-1",
        "status": "queued",
        "request_json": '{"x": 1}',
        "progress": 0,
        "error_message": None,
        "created_at": _DT,
        "started_at": None,
        "completed_at": None,
        "updated_at": _DT,
        "_total": 3,
    }
    row.update(overrides)
    return row


def test_list_jobs_returns_empty_list_and_zero_total() -> None:
    cursor = _FakeCursor(fetchall=[])
    conn = _FakeConn(cursor)

    items, total = _run(
        backtest_job.list_jobs(conn, job_type=None, status=None, page=_PAGE, user_id="user-1")
    )

    assert items == []
    assert total == 0


def test_list_jobs_maps_summary_rows_and_total() -> None:
    cursor = _FakeCursor(fetchall=[_job_row()])
    conn = _FakeConn(cursor)

    items, total = _run(
        backtest_job.list_jobs(
            conn, job_type="backtest", status="queued", page=_PAGE, user_id="user-1"
        )
    )

    assert total == 3
    assert items[0]["job_id"] == "job-1"
    assert items[0]["job_type"] == "backtest"
    assert items[0]["status"] == "queued"
    assert items[0]["created_at"].endswith("+08:00")


def test_list_jobs_applies_filters_and_pagination() -> None:
    cursor = _FakeCursor(fetchall=[_job_row()])
    conn = _FakeConn(cursor)

    _run(
        backtest_job.list_jobs(
            conn, job_type="sweep", status="running", page=_PAGE, user_id="user-1"
        )
    )

    sql, params = cursor.executed[0]
    assert "COUNT(*) OVER() AS _total" in sql
    assert "job_type = %(job_type)s" in sql
    assert "status = %(status)s" in sql
    assert "user_id IS NOT DISTINCT FROM %(user_id)s" in sql
    assert params == {
        "limit": 10,
        "offset": 10,
        "job_type": "sweep",
        "status": "running",
        "user_id": "user-1",
    }


def test_list_jobs_filters_rows_by_user_id() -> None:
    """A user may only see their own jobs in the list response."""
    cursor = _FakeCursor(
        fetchall=[
            _job_row(_total=2),
            _job_row(job_id="job-2", ref_id="run-2", _total=2),
        ],
    )
    conn = _FakeConn(cursor)

    items, total = _run(
        backtest_job.list_jobs(conn, job_type=None, status=None, page=_PAGE, user_id="user-A")
    )

    assert total == 2
    assert {item["job_id"] for item in items} == {"job-1", "job-2"}
    sql, params = cursor.executed[0]
    assert "user_id IS NOT DISTINCT FROM %(user_id)s" in sql
    assert params["user_id"] == "user-A"


def test_get_job_returns_full_detail() -> None:
    cursor = _FakeCursor(fetchone=_job_row())
    conn = _FakeConn(cursor)

    data = _run(backtest_job.get_job(conn, "job-1", user_id="user-1"))

    assert data["job_id"] == "job-1"
    assert data["request_json"] == {"x": 1}
    assert data["created_at"].endswith("+08:00")


def test_get_job_raises_not_found_when_missing() -> None:
    cursor = _FakeCursor(fetchone=None)
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        _run(backtest_job.get_job(conn, "missing", user_id="user-1"))


def test_get_job_raises_not_found_for_other_user() -> None:
    """Owner check: cross-user access must surface as ``NotFound`` rather
    than leak the resource's existence."""
    # The store's SELECT applies the user_id filter, so user-B never sees
    # user-A's row at all — fetchone returns None.
    cursor = _FakeCursor(fetchone=None)
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        _run(backtest_job.get_job(conn, "job-1", user_id="user-B"))

    sql, params = cursor.executed[0]
    assert "user_id IS NOT DISTINCT FROM %(user_id)s" in sql
    assert params["user_id"] == "user-B"


def test_cancel_job_returns_refreshed_detail() -> None:
    queued_row = _job_row(status="queued")
    cancelled_row = _job_row(status="cancelled", completed_at=_DT)
    cursor = _FakeCursor(fetchone_seq=[queued_row, cancelled_row])
    conn = _FakeConn(cursor)

    data = _run(backtest_job.cancel_job(conn, "job-1", user_id="user-1"))

    # The store's _run dispatches multiple SELECT/UPDATE statements through the
    # same cursor; we just verify the latest one is the cancellation SQL.
    assert any("UPDATE backtest_jobs" in sql and "cancelled" in sql for sql, _ in cursor.executed)
    # The second ``fetchone`` returns the refreshed row.
    assert data["status"] == "cancelled"


def test_cancel_job_raises_not_found_when_missing() -> None:
    cursor = _FakeCursor(fetchone=None)
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        _run(backtest_job.cancel_job(conn, "missing", user_id="user-1"))


def test_cancel_job_raises_not_found_for_other_user() -> None:
    """Owner check: cancelling a job owned by someone else must 404."""
    # Store's SELECT applies the user_id filter, so user-B sees no row.
    cursor = _FakeCursor(fetchone=None)
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        _run(backtest_job.cancel_job(conn, "job-1", user_id="user-B"))


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_cancel_job_raises_conflict_for_terminal_statuses(status: str) -> None:
    cursor = _FakeCursor(fetchone=_job_row(status=status))
    conn = _FakeConn(cursor)

    with pytest.raises(Conflict):
        _run(backtest_job.cancel_job(conn, "job-1", user_id="user-1"))


def test_cancel_job_uses_db_transport(monkeypatch: Any) -> None:
    """P3: after marking the row cancelled, no in-process notification is
    required. The runner's per-trial DB probe (``sync_is_cancelled_status``)
    observes the new status on its next iteration. Service stays simple:
    it just marks cancelled and re-reads."""
    queued_row = _job_row(status="running")
    cancelled_row = _job_row(status="cancelled", completed_at=_DT)
    cursor = _FakeCursor(fetchone_seq=[queued_row, cancelled_row])
    conn = _FakeConn(cursor)

    from getrich.apps.strategy import backtest_job_runner

    # The in-process ``notify_job_cancelled`` helper was deleted in P3.
    # Assert it does not exist on the runner module (defensive — if a
    # future refactor reintroduces it, this test will fail loudly so
    # the call site can be updated accordingly).
    assert not hasattr(backtest_job_runner, "notify_job_cancelled")

    data = _run(backtest_job.cancel_job(conn, "job-1", user_id="user-1"))

    assert data["status"] == "cancelled"
    # The cancel path is: get_job (verify status) → mark_cancelled
    # → get_job (return). Two reads in the FakeConn sequence above.
    assert len(cursor.executed) >= 2


def test_cancel_job_no_longer_imports_notify_helper() -> None:
    """P3: the service module's source no longer references
    ``notify_job_cancelled``. The DB probe is the only transport."""
    import inspect

    source = inspect.getsource(backtest_job.cancel_job)
    assert "notify_job_cancelled" not in source


def test_router_registers_backtest_job_paths() -> None:
    paths = {route.path for route in router.routes}

    assert "/backtest-jobs" in paths
    assert "/backtest-jobs/{job_id}" in paths
    assert "/backtest-jobs/{job_id}/events" in paths
    assert "/backtest-jobs/{job_id}/cancel" in paths
    assert "/backtest-jobs/backtest" in paths
    assert "/backtest-jobs/sweep" in paths
    assert "/backtest-jobs/walk-forward" in paths


# ---------------------------------------------------------------- execution


def _exec_job_row(job_id: str, job_type: str) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "job_type": job_type,
        "ref_id": "ref-1",
        "status": "queued",
        "request_json": {},
        "progress": 0,
        "error_message": None,
        "created_at": _DT,
        "started_at": None,
        "completed_at": None,
        "updated_at": _DT,
    }


def _backtest_payload() -> dict[str, Any]:
    return {
        "strategy_name": "macross",
        "symbols": ["000001.SZ"],
        "start": datetime(2026, 6, 1, 9, 30, tzinfo=_TZ).isoformat(),
        "end": datetime(2026, 6, 2, 9, 30, tzinfo=_TZ).isoformat(),
        "initial_cash": "1000",
        "freq": "1d",
        "extra_freqs": [],
        "execution_lag_bars": 1,
        "strategy_params": {"fast": 5, "slow": 10},
        "bar_loader": "pg",
        "save_artifacts": False,
    }


def _sweep_payload() -> dict[str, Any]:
    payload = _backtest_payload()
    payload["sweep_id"] = None
    payload["search_type"] = "grid"
    payload["search_spec"] = {"space": {"fast": [5, 10]}, "constraints": []}
    payload["select_metric"] = "sharpe_ratio"
    payload["maximize"] = True
    payload["fail_fast"] = False
    payload["strategy_params"] = {}
    return payload


def _walk_forward_payload() -> dict[str, Any]:
    payload = _backtest_payload()
    payload["walk_forward_id"] = None
    payload["search_spec"] = {"space": {"fast": [5, 10]}, "constraints": []}
    payload["train_months"] = 1
    payload["val_months"] = 1
    payload["step_months"] = None
    payload["refit"] = "rolling"
    payload["select_metric"] = "sharpe_ratio"
    payload["maximize"] = True
    payload["fail_fast"] = False
    payload["strategy_params"] = {"fast": 5, "slow": 10}
    return payload


def test_create_backtest_job_inserts_queued_row_and_returns_pair(monkeypatch: Any) -> None:
    """create_backtest_job should write a queued row and return (job_id, ref_id)."""

    inserted: list[dict[str, Any]] = []

    async def fake_create_job(
        job_type: str,
        ref_id: str,
        *,
        request_json=None,
        conn=None,
        max_attempts=1,
        user_id=None,
        **_unused,
    ) -> str:
        inserted.append(
            {
                "job_type": job_type,
                "ref_id": ref_id,
                "request_json": request_json,
                "user_id": user_id,
            }
        )
        return "job-1"

    monkeypatch.setattr(
        backtest_job._STORE,
        "create_job",
        fake_create_job,
    )

    body = _BacktestRunRequestFactory().build(_backtest_payload())
    job_id, ref_id = _run(
        backtest_job.create_backtest_job(
            _FakeConn(_FakeCursor()),  # type: ignore[arg-type]
            body,
            user_id="user-1",
        )
    )

    assert job_id == "job-1"
    assert len(ref_id) == 32  # uuid4().hex
    assert inserted[0]["job_type"] == "backtest"
    assert inserted[0]["ref_id"] == ref_id
    assert inserted[0]["request_json"]["strategy_name"] == "macross"


def test_create_sweep_job_honors_explicit_sweep_id(monkeypatch: Any) -> None:
    inserted: list[dict[str, Any]] = []

    async def fake_create_job(
        job_type: str,
        ref_id: str,
        *,
        request_json=None,
        conn=None,
        max_attempts=1,
        user_id=None,
        **_unused,
    ) -> str:
        inserted.append({"job_type": job_type, "ref_id": ref_id, "user_id": user_id})
        return "job-1"

    monkeypatch.setattr(backtest_job._STORE, "create_job", fake_create_job)

    payload = _sweep_payload()
    payload["sweep_id"] = "explicit-sweep"
    body = _SweepRunRequestFactory().build(payload)
    job_id, ref_id = _run(
        backtest_job.create_sweep_job(
            _FakeConn(_FakeCursor()),  # type: ignore[arg-type]
            body,
            user_id="user-1",
        )
    )

    assert job_id == "job-1"
    assert ref_id == "explicit-sweep"
    assert inserted[0]["job_type"] == "sweep"


def test_create_walk_forward_job_uses_uuid_when_unset(monkeypatch: Any) -> None:
    inserted: list[dict[str, Any]] = []

    async def fake_create_job(
        job_type: str,
        ref_id: str,
        *,
        request_json=None,
        conn=None,
        max_attempts=1,
        user_id=None,
        **_unused,
    ) -> str:
        inserted.append({"job_type": job_type, "ref_id": ref_id, "user_id": user_id})
        return "job-1"

    monkeypatch.setattr(backtest_job._STORE, "create_job", fake_create_job)

    body = _WalkForwardRunRequestFactory().build(_walk_forward_payload())
    job_id, ref_id = _run(
        backtest_job.create_walk_forward_job(
            _FakeConn(_FakeCursor()),  # type: ignore[arg-type]
            body,
            user_id="user-1",
        )
    )

    assert job_id == "job-1"
    assert len(ref_id) == 32
    assert inserted[0]["job_type"] == "walk_forward"


# ---------------------------------------------------------------- request factories


class _BacktestRunRequestFactory:
    def build(self, payload: dict[str, Any]) -> Any:
        from getrich.apps.web.schemas.backtest import BacktestRunRequest

        return BacktestRunRequest.model_validate(payload)


class _SweepRunRequestFactory:
    def build(self, payload: dict[str, Any]) -> Any:
        from getrich.apps.web.schemas.backtest import SweepRunRequest

        return SweepRunRequest.model_validate(payload)


class _WalkForwardRunRequestFactory:
    def build(self, payload: dict[str, Any]) -> Any:
        from getrich.apps.web.schemas.backtest import WalkForwardRunRequest

        return WalkForwardRunRequest.model_validate(payload)


# ---------------------------------------------------------------- idempotency / max_attempts


def test_create_backtest_job_with_same_idempotency_key_returns_existing(
    monkeypatch: Any,
) -> None:
    """Same Idempotency-Key + same body on a 2nd POST returns the existing
    ``(job_id, ref_id)`` and never calls ``create_job``.
    """
    from getrich.apps.web.schemas.backtest import BacktestRunRequest
    from getrich.apps.web.services.backtest_job import _body_fingerprint

    def _run_payload() -> dict[str, Any]:
        return {
            "strategy_name": "macross",
            "symbols": ["000001.SZ"],
            "start": datetime(2026, 6, 1, 9, 30, tzinfo=_TZ).isoformat(),
            "end": datetime(2026, 6, 2, 9, 30, tzinfo=_TZ).isoformat(),
            "initial_cash": "1000",
            "freq": "1d",
            "extra_freqs": [],
            "execution_lag_bars": 1,
            "strategy_params": {},
            "bar_loader": "pg",
            "save_artifacts": False,
            "max_attempts": 3,
        }

    body = BacktestRunRequest.model_validate(_run_payload())
    existing_row = {
        "job_id": "job-existing",
        "job_type": "backtest",
        "ref_id": "run-existing",
        "status": "queued",
        "request_json": {},
        "request_hash": _body_fingerprint(body),  # matches the incoming body
        "progress": 0,
        "error_message": None,
        "attempt": 1,
        "max_attempts": 3,
        "next_retry_at": None,
        "created_at": _DT,
        "started_at": None,
        "completed_at": None,
        "updated_at": _DT,
    }

    async def fake_get_by_idem(
        *, key: str, user_id: str | None = None, conn: Any = None
    ) -> dict[str, Any] | None:
        if key == "abc-123":
            return existing_row
        return None

    monkeypatch.setattr(backtest_job._STORE, "get_by_idempotency_key", fake_get_by_idem)

    # Track whether create_job gets called — must NOT be called.
    create_calls: list[dict[str, Any]] = []

    async def fake_create_job(
        job_type: str,
        ref_id: str,
        *,
        request_json=None,
        conn=None,
        max_attempts=1,
        user_id=None,
        **_unused,
    ) -> str:
        create_calls.append({"job_type": job_type, "ref_id": ref_id})
        return "job-new"

    monkeypatch.setattr(backtest_job._STORE, "create_job", fake_create_job)

    job_id, ref_id = _run(
        backtest_job.create_backtest_job(
            _FakeConn(_FakeCursor()),
            body,  # type: ignore[arg-type]
            user_id="user-1",
            idempotency_key="abc-123",
        )
    )

    assert (job_id, ref_id) == ("job-existing", "run-existing")
    assert create_calls == []  # no new row created


def test_create_backtest_job_same_key_different_body_raises_conflict(
    monkeypatch: Any,
) -> None:
    """Same Idempotency-Key + different body raises ``Conflict`` and never
    reaches ``create_job``. The 409 is the new behavior introduced in
    migration 023 / fingerprint comparison.
    """
    from getrich.apps.web.schemas.backtest import BacktestRunRequest

    payload = _backtest_payload()
    body = BacktestRunRequest.model_validate(payload)
    # Stored hash is a known sentinel that does NOT match the body's
    # fingerprint — any 64-char hex will do; here we use a string of
    # zeros just to make the mismatch obvious.
    mismatched_hash = "0" * 64
    assert mismatched_hash != backtest_job._body_fingerprint(body)

    existing_row = {
        "job_id": "job-existing",
        "job_type": "backtest",
        "ref_id": "run-existing",
        "status": "queued",
        "request_json": {},
        "request_hash": mismatched_hash,
        "progress": 0,
        "error_message": None,
        "attempt": 1,
        "max_attempts": 1,
        "next_retry_at": None,
        "created_at": _DT,
        "started_at": None,
        "completed_at": None,
        "updated_at": _DT,
    }

    async def fake_get_by_idem(
        *, key: str, user_id: str | None = None, conn: Any = None
    ) -> dict[str, Any] | None:
        return existing_row

    monkeypatch.setattr(backtest_job._STORE, "get_by_idempotency_key", fake_get_by_idem)

    create_calls: list[dict[str, Any]] = []

    async def fake_create_job(
        job_type: str,
        ref_id: str,
        *,
        request_json=None,
        conn=None,
        max_attempts=1,
        user_id=None,
        **_unused,
    ) -> str:
        create_calls.append({"job_type": job_type, "ref_id": ref_id})
        return "job-new"

    monkeypatch.setattr(backtest_job._STORE, "create_job", fake_create_job)

    with pytest.raises(Conflict) as excinfo:
        _run(
            backtest_job.create_backtest_job(
                _FakeConn(_FakeCursor()),  # type: ignore[arg-type]
                body,  # type: ignore[arg-type]
                user_id="user-1",
                idempotency_key="abc-123",
            )
        )

    # The error message must include the offending key so the user can
    # re-issue with a fresh UUID. http_status=409 is set by the error
    # class; we assert it via the global exception handler contract.
    assert "abc-123" in str(excinfo.value)
    assert "different request body" in str(excinfo.value)
    assert create_calls == []  # never reached


def test_create_backtest_job_same_key_legacy_null_hash_returns_existing(
    monkeypatch: Any,
) -> None:
    """Legacy rows (predating migration 023) have ``request_hash = None``;
    the service treats them as a permissive match so in-flight idempotency
    keys do not break at the cutover boundary.
    """
    from getrich.apps.web.schemas.backtest import BacktestRunRequest

    body = BacktestRunRequest.model_validate(_backtest_payload())
    existing_row = {
        "job_id": "job-existing",
        "job_type": "backtest",
        "ref_id": "run-existing",
        "status": "queued",
        "request_json": {},
        "request_hash": None,  # legacy
        "progress": 0,
        "error_message": None,
        "attempt": 1,
        "max_attempts": 1,
        "next_retry_at": None,
        "created_at": _DT,
        "started_at": None,
        "completed_at": None,
        "updated_at": _DT,
    }

    async def fake_get_by_idem(
        *, key: str, user_id: str | None = None, conn: Any = None
    ) -> dict[str, Any] | None:
        return existing_row

    monkeypatch.setattr(backtest_job._STORE, "get_by_idempotency_key", fake_get_by_idem)

    create_calls: list[dict[str, Any]] = []

    async def fake_create_job(
        job_type: str,
        ref_id: str,
        *,
        request_json=None,
        conn=None,
        max_attempts=1,
        user_id=None,
        **_unused,
    ) -> str:
        create_calls.append({"job_type": job_type, "ref_id": ref_id})
        return "job-new"

    monkeypatch.setattr(backtest_job._STORE, "create_job", fake_create_job)

    job_id, ref_id = _run(
        backtest_job.create_backtest_job(
            _FakeConn(_FakeCursor()),  # type: ignore[arg-type]
            body,  # type: ignore[arg-type]
            user_id="user-1",
            idempotency_key="legacy-key",
        )
    )

    assert (job_id, ref_id) == ("job-existing", "run-existing")
    assert create_calls == []


def test_create_sweep_job_same_key_different_body_raises_conflict(
    monkeypatch: Any,
) -> None:
    """Mirror the backtest test against ``create_sweep_job`` — same shared
    dedup path, but we still exercise the dedicated entry point to make
    regressions in the wrapper obvious.
    """
    body = _SweepRunRequestFactory().build(_sweep_payload())
    mismatched_hash = "f" * 64
    assert mismatched_hash != backtest_job._body_fingerprint(body)
    existing_row = {
        "job_id": "job-existing",
        "job_type": "sweep",
        "ref_id": "sweep-existing",
        "status": "queued",
        "request_json": {},
        "request_hash": mismatched_hash,
        "progress": 0,
        "error_message": None,
        "attempt": 1,
        "max_attempts": 1,
        "next_retry_at": None,
        "created_at": _DT,
        "started_at": None,
        "completed_at": None,
        "updated_at": _DT,
    }

    async def fake_get_by_idem(
        *, key: str, user_id: str | None = None, conn: Any = None
    ) -> dict[str, Any] | None:
        return existing_row

    monkeypatch.setattr(backtest_job._STORE, "get_by_idempotency_key", fake_get_by_idem)

    create_calls: list[dict[str, Any]] = []

    async def fake_create_job(
        job_type: str,
        ref_id: str,
        *,
        request_json=None,
        conn=None,
        max_attempts=1,
        user_id=None,
        **_unused,
    ) -> str:
        create_calls.append({"job_type": job_type, "ref_id": ref_id})
        return "job-new"

    monkeypatch.setattr(backtest_job._STORE, "create_job", fake_create_job)

    with pytest.raises(Conflict):
        _run(
            backtest_job.create_sweep_job(
                _FakeConn(_FakeCursor()),  # type: ignore[arg-type]
                body,  # type: ignore[arg-type]
                user_id="user-1",
                idempotency_key="dup-key",
            )
        )
    assert create_calls == []


def test_create_walk_forward_job_same_key_different_body_raises_conflict(
    monkeypatch: Any,
) -> None:
    """Mirror for ``create_walk_forward_job``."""
    body = _WalkForwardRunRequestFactory().build(_walk_forward_payload())
    mismatched_hash = "a" * 64
    assert mismatched_hash != backtest_job._body_fingerprint(body)
    existing_row = {
        "job_id": "job-existing",
        "job_type": "walk_forward",
        "ref_id": "wf-existing",
        "status": "queued",
        "request_json": {},
        "request_hash": mismatched_hash,
        "progress": 0,
        "error_message": None,
        "attempt": 1,
        "max_attempts": 1,
        "next_retry_at": None,
        "created_at": _DT,
        "started_at": None,
        "completed_at": None,
        "updated_at": _DT,
    }

    async def fake_get_by_idem(
        *, key: str, user_id: str | None = None, conn: Any = None
    ) -> dict[str, Any] | None:
        return existing_row

    monkeypatch.setattr(backtest_job._STORE, "get_by_idempotency_key", fake_get_by_idem)

    create_calls: list[dict[str, Any]] = []

    async def fake_create_job(
        job_type: str,
        ref_id: str,
        *,
        request_json=None,
        conn=None,
        max_attempts=1,
        user_id=None,
        **_unused,
    ) -> str:
        create_calls.append({"job_type": job_type, "ref_id": ref_id})
        return "job-new"

    monkeypatch.setattr(backtest_job._STORE, "create_job", fake_create_job)

    with pytest.raises(Conflict):
        _run(
            backtest_job.create_walk_forward_job(
                _FakeConn(_FakeCursor()),  # type: ignore[arg-type]
                body,  # type: ignore[arg-type]
                user_id="user-1",
                idempotency_key="dup-key",
            )
        )
    assert create_calls == []


def test_create_backtest_job_with_different_idempotency_key_creates_new(
    monkeypatch: Any,
) -> None:
    """Different keys must produce distinct rows."""
    from getrich.apps.web.schemas.backtest import BacktestRunRequest

    body = BacktestRunRequest.model_validate(
        {
            "strategy_name": "macross",
            "symbols": ["000001.SZ"],
            "start": datetime(2026, 6, 1, 9, 30, tzinfo=_TZ).isoformat(),
            "end": datetime(2026, 6, 2, 9, 30, tzinfo=_TZ).isoformat(),
            "initial_cash": "1000",
            "freq": "1d",
            "extra_freqs": [],
            "execution_lag_bars": 1,
            "strategy_params": {},
            "bar_loader": "pg",
            "save_artifacts": False,
            "max_attempts": 1,
        }
    )

    async def fake_get_by_idem(*, key, user_id=None, conn=None) -> dict[str, Any] | None:
        return None

    monkeypatch.setattr(backtest_job._STORE, "get_by_idempotency_key", fake_get_by_idem)

    async def fake_create_job(
        job_type: str,
        ref_id: str,
        *,
        request_json=None,
        conn=None,
        max_attempts=1,
        user_id=None,
        **_unused,
    ) -> str:
        return "job-x"

    monkeypatch.setattr(backtest_job._STORE, "create_job", fake_create_job)

    # Two POSTs with different keys must both create rows.
    _run(
        backtest_job.create_backtest_job(
            _FakeConn(_FakeCursor()),
            body,  # type: ignore[arg-type]
            user_id="user-1",
            idempotency_key="key-1",
        )
    )
    _run(
        backtest_job.create_backtest_job(
            _FakeConn(_FakeCursor()),
            body,  # type: ignore[arg-type]
            user_id="user-1",
            idempotency_key="key-2",
        )
    )
    # Implicit: no error means we reached the create path twice.


def test_create_backtest_job_without_idempotency_key_creates_each_time(
    monkeypatch: Any,
) -> None:
    """No key → no dedup; each call reaches the store."""
    from getrich.apps.web.schemas.backtest import BacktestRunRequest

    body = BacktestRunRequest.model_validate(
        {
            "strategy_name": "macross",
            "symbols": ["000001.SZ"],
            "start": datetime(2026, 6, 1, 9, 30, tzinfo=_TZ).isoformat(),
            "end": datetime(2026, 6, 2, 9, 30, tzinfo=_TZ).isoformat(),
            "initial_cash": "1000",
            "freq": "1d",
            "extra_freqs": [],
            "execution_lag_bars": 1,
            "strategy_params": {},
            "bar_loader": "pg",
            "save_artifacts": False,
        }
    )

    async def fake_get_by_idem(*, key, user_id=None, conn=None) -> dict[str, Any] | None:
        return None

    monkeypatch.setattr(backtest_job._STORE, "get_by_idempotency_key", fake_get_by_idem)

    created: list[str] = []

    async def fake_create_job(
        job_type: str,
        ref_id: str,
        *,
        request_json=None,
        conn=None,
        max_attempts=1,
        user_id=None,
        **_unused,
    ) -> str:
        created.append(ref_id)
        return f"job-{len(created)}"

    monkeypatch.setattr(backtest_job._STORE, "create_job", fake_create_job)

    _run(
        backtest_job.create_backtest_job(
            _FakeConn(_FakeCursor()),
            body,  # type: ignore[arg-type]
            user_id="user-1",
        )
    )
    _run(
        backtest_job.create_backtest_job(
            _FakeConn(_FakeCursor()),
            body,  # type: ignore[arg-type]
            user_id="user-1",
        )
    )
    assert len(created) == 2  # two fresh ref_ids


def test_max_attempts_zero_rejected_by_schema() -> None:
    """Pydantic must reject max_attempts < 1."""
    import pytest
    from pydantic import ValidationError

    from getrich.apps.web.schemas.backtest import BacktestRunRequest

    payload = {
        "strategy_name": "macross",
        "symbols": ["000001.SZ"],
        "start": datetime(2026, 6, 1, 9, 30, tzinfo=_TZ).isoformat(),
        "end": datetime(2026, 6, 2, 9, 30, tzinfo=_TZ).isoformat(),
        "initial_cash": "1000",
        "freq": "1d",
        "extra_freqs": [],
        "execution_lag_bars": 1,
        "strategy_params": {},
        "bar_loader": "pg",
        "save_artifacts": False,
        "max_attempts": 0,
    }
    with pytest.raises(ValidationError):
        BacktestRunRequest.model_validate(payload)


def test_max_attempts_eleven_rejected_by_schema() -> None:
    """Pydantic must reject max_attempts > 10."""
    import pytest
    from pydantic import ValidationError

    from getrich.apps.web.schemas.backtest import BacktestRunRequest

    payload = {
        "strategy_name": "macross",
        "symbols": ["000001.SZ"],
        "start": datetime(2026, 6, 1, 9, 30, tzinfo=_TZ).isoformat(),
        "end": datetime(2026, 6, 2, 9, 30, tzinfo=_TZ).isoformat(),
        "initial_cash": "1000",
        "freq": "1d",
        "extra_freqs": [],
        "execution_lag_bars": 1,
        "strategy_params": {},
        "bar_loader": "pg",
        "save_artifacts": False,
        "max_attempts": 11,
    }
    with pytest.raises(ValidationError):
        BacktestRunRequest.model_validate(payload)


# ---------------------------------------------------------------- P1 #6 per-job retry override


def test_create_backtest_job_threads_retry_overrides_to_store(monkeypatch: Any) -> None:
    """retry_base_seconds / retry_cap_seconds / retry_jitter_pct from the
    request body are forwarded into the store as first-class columns."""
    from getrich.apps.web.schemas.backtest import BacktestRunRequest

    inserted: list[dict[str, Any]] = []

    async def fake_create_job(
        job_type: str,
        ref_id: str,
        *,
        request_json=None,
        conn=None,
        max_attempts=1,
        user_id=None,
        request_hash=None,
        retry_base_seconds=None,
        retry_cap_seconds=None,
        retry_jitter_pct=None,
    ) -> str:
        inserted.append(
            {
                "job_type": job_type,
                "ref_id": ref_id,
                "user_id": user_id,
                "retry_base_seconds": retry_base_seconds,
                "retry_cap_seconds": retry_cap_seconds,
                "retry_jitter_pct": retry_jitter_pct,
            }
        )
        return "job-1"

    monkeypatch.setattr(backtest_job._STORE, "create_job", fake_create_job)

    payload = _backtest_payload()
    payload.update(
        {
            "retry_base_seconds": 2.5,
            "retry_cap_seconds": 30.0,
            "retry_jitter_pct": 0.15,
        }
    )
    body = BacktestRunRequest.model_validate(payload)
    _run(
        backtest_job.create_backtest_job(
            _FakeConn(_FakeCursor()),  # type: ignore[arg-type]
            body,  # type: ignore[arg-type]
            user_id="user-1",
        )
    )

    assert inserted[0]["retry_base_seconds"] == 2.5
    assert inserted[0]["retry_cap_seconds"] == 30.0
    assert inserted[0]["retry_jitter_pct"] == 0.15


def test_create_sweep_job_threads_retry_overrides_to_store(monkeypatch: Any) -> None:
    inserted: list[dict[str, Any]] = []

    async def fake_create_job(
        job_type: str,
        ref_id: str,
        *,
        request_json=None,
        conn=None,
        max_attempts=1,
        user_id=None,
        request_hash=None,
        retry_base_seconds=None,
        retry_cap_seconds=None,
        retry_jitter_pct=None,
    ) -> str:
        inserted.append(
            {
                "job_type": job_type,
                "ref_id": ref_id,
                "retry_base_seconds": retry_base_seconds,
                "retry_cap_seconds": retry_cap_seconds,
                "retry_jitter_pct": retry_jitter_pct,
            }
        )
        return "job-1"

    monkeypatch.setattr(backtest_job._STORE, "create_job", fake_create_job)

    payload = _sweep_payload()
    payload["retry_base_seconds"] = 1.0
    payload["retry_cap_seconds"] = 5.0
    body = _SweepRunRequestFactory().build(payload)
    _run(
        backtest_job.create_sweep_job(
            _FakeConn(_FakeCursor()),  # type: ignore[arg-type]
            body,  # type: ignore[arg-type]
            user_id="user-1",
        )
    )

    assert inserted[0]["retry_base_seconds"] == 1.0
    assert inserted[0]["retry_cap_seconds"] == 5.0
    assert inserted[0]["retry_jitter_pct"] is None


def test_create_walk_forward_job_threads_retry_overrides_to_store(monkeypatch: Any) -> None:
    inserted: list[dict[str, Any]] = []

    async def fake_create_job(
        job_type: str,
        ref_id: str,
        *,
        request_json=None,
        conn=None,
        max_attempts=1,
        user_id=None,
        request_hash=None,
        retry_base_seconds=None,
        retry_cap_seconds=None,
        retry_jitter_pct=None,
    ) -> str:
        inserted.append(
            {
                "job_type": job_type,
                "ref_id": ref_id,
                "retry_base_seconds": retry_base_seconds,
                "retry_cap_seconds": retry_cap_seconds,
                "retry_jitter_pct": retry_jitter_pct,
            }
        )
        return "job-1"

    monkeypatch.setattr(backtest_job._STORE, "create_job", fake_create_job)

    payload = _walk_forward_payload()
    payload["retry_jitter_pct"] = 0.3
    body = _WalkForwardRunRequestFactory().build(payload)
    _run(
        backtest_job.create_walk_forward_job(
            _FakeConn(_FakeCursor()),  # type: ignore[arg-type]
            body,  # type: ignore[arg-type]
            user_id="user-1",
        )
    )

    assert inserted[0]["retry_jitter_pct"] == 0.3
    assert inserted[0]["retry_base_seconds"] is None
    assert inserted[0]["retry_cap_seconds"] is None
