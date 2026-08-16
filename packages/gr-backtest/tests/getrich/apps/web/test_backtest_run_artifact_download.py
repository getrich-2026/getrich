"""Integration tests for the backtest artifact binary download endpoint.

This module mounts the existing ``backtest_runs`` router on a minimal
``FastAPI`` app so the new ``/content`` endpoint can be exercised end-to-end
without standing up the real PostgreSQL connection pool. The ``get_db`` and
``require_user`` dependencies are overridden with fakes that return a
deterministic owner / artifact row from in-memory cursors.

The tests verify the security boundary: anonymous → 401, cross-user → 404,
HTTPS URI → 400, path traversal → 404, valid owner → 200 + bytes.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from getrich.apps.web.deps import get_db, require_user
from getrich.apps.web.response import register_exception_handlers
from getrich.apps.web.routers.backtest_runs import backtest_storage_dep, router
from gr_data.config.settings import BacktestStorageConfig


_TZ = ZoneInfo("Asia/Shanghai")
_DT = datetime(2026, 1, 2, 9, 30, tzinfo=_TZ)
_AUTH = "Bearer test-token"


class _FakeCursor:
    def __init__(
        self,
        *,
        fetchone_seq: list[dict[str, Any] | None] | None = None,
    ) -> None:
        self.executed: list[tuple[str, dict[str, Any] | None]] = []
        self._fetchone_seq = fetchone_seq or []
        self._idx = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, sql: str, params: dict[str, Any] | None = None) -> None:
        self.executed.append((sql, params))

    async def fetchone(self) -> dict[str, Any] | None:
        if self._idx >= len(self._fetchone_seq):
            return None
        value = self._fetchone_seq[self._idx]
        self._idx += 1
        return value

    async def fetchall(self) -> list[dict[str, Any]]:
        return []


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _FakeCursor:
        return self._cursor


def _run_row(user_id: str = "user-1") -> dict[str, Any]:
    return {
        "run_id": "run-1",
        "user_id": user_id,
        "strategy_id": "strategy-1",
        "strategy_name": "DemoStrategy",
        "strategy_names": '["DemoStrategy"]',
        "config_fingerprint": "fp-1",
        "config": '{"initial_cash":"1000"}',
        "symbols": '["000001.SZ"]',
        "freq": "1d",
        "start_at": _DT,
        "end_at": _DT,
        "initial_cash": None,
        "final_cash": None,
        "final_equity": None,
        "benchmark_final_equity": None,
        "status": "completed",
        "error_message": None,
        "created_at": _DT,
        "completed_at": _DT,
        "updated_at": _DT,
    }


def _artifact_row(uri: str, user_id: str = "user-1") -> dict[str, Any]:
    return {
        "id": "artifact-1",
        "run_id": "run-1",
        "artifact_type": "manifest",
        "uri": uri,
        "checksum": None,
        "meta": "{}",
        "created_at": _DT,
    }


def _build_app(
    *,
    run_seq: list[dict[str, Any] | None],
    auth_user: str | None,
    storage: BacktestStorageConfig,
) -> FastAPI:
    """Construct a minimal app where the backtest_runs router's deps are faked."""
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    # Translate ApiError exceptions to JSON HTTP responses, matching the
    # production main.app setup.
    register_exception_handlers(app)
    # Reset overrides to make test isolation robust.
    app.dependency_overrides.clear()
    cursor_holder: dict[str, _FakeCursor] = {}

    def _override_get_db() -> Any:
        cursor = _FakeCursor(fetchone_seq=list(run_seq))
        cursor_holder["cursor"] = cursor
        return _FakeConn(cursor)

    def _override_storage() -> BacktestStorageConfig:
        return storage

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[backtest_storage_dep] = _override_storage
    if auth_user is not None:

        async def _override_require_user() -> str:
            return auth_user

        app.dependency_overrides[require_user] = _override_require_user

    # Stash the cursor for test inspection.
    app.state.fake_cursor_holder = cursor_holder  # type: ignore[attr-defined]
    return app


def test_get_artifact_content_returns_file_bytes(tmp_path: Path) -> None:
    """Owner downloads a local file -> 200 with bytes equal to the file content."""
    payload = b'{"runs": 1, "ok": true}\n'
    target = tmp_path / "manifest.json"
    target.write_bytes(payload)

    # Point the artifact row at the file (owner=user-1).
    app = _build_app(
        run_seq=[_run_row("user-1"), _artifact_row(str(target), "user-1")],
        auth_user="user-1",
        storage=BacktestStorageConfig(artifact_dir=tmp_path),
    )

    with TestClient(app) as client:
        resp = client.get(
            "/v1/backtest-runs/run-1/artifacts/artifact-1/content",
            headers={"Authorization": _AUTH},
        )

    assert resp.status_code == 200
    assert resp.content == payload
    cd = resp.headers["Content-Disposition"]
    assert "attachment" in cd
    assert "manifest.json" in cd
    assert resp.headers["Content-Length"] == str(len(payload))
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["content-type"].startswith("application/json")


def test_get_artifact_content_404_for_other_user(tmp_path: Path) -> None:
    """Cross-user: token=user-B but the run is owned by user-A -> 404."""
    target = tmp_path / "manifest.json"
    target.write_bytes(b"{}")

    app = _build_app(
        run_seq=[_run_row("user-A")],  # owner check sees user-A, requester is user-B
        auth_user="user-B",
        storage=BacktestStorageConfig(artifact_dir=tmp_path),
    )

    with TestClient(app) as client:
        resp = client.get(
            "/v1/backtest-runs/run-1/artifacts/artifact-1/content",
            headers={"Authorization": _AUTH},
        )

    assert resp.status_code == 404


def test_get_artifact_content_404_when_artifact_missing(tmp_path: Path) -> None:
    """Owner passes but no artifact row -> 404."""
    app = _build_app(
        run_seq=[_run_row("user-1"), None],
        auth_user="user-1",
        storage=BacktestStorageConfig(artifact_dir=tmp_path),
    )

    with TestClient(app) as client:
        resp = client.get(
            "/v1/backtest-runs/run-1/artifacts/missing/content",
            headers={"Authorization": _AUTH},
        )

    assert resp.status_code == 404


def test_get_artifact_content_400_for_https_uri(tmp_path: Path) -> None:
    """Non-local scheme must be rejected (no SSRF / proxy leak)."""
    app = _build_app(
        run_seq=[_run_row("user-1"), _artifact_row("https://example.com/secret", "user-1")],
        auth_user="user-1",
        storage=BacktestStorageConfig(artifact_dir=tmp_path),
    )

    with TestClient(app) as client:
        resp = client.get(
            "/v1/backtest-runs/run-1/artifacts/artifact-1/content",
            headers={"Authorization": _AUTH},
        )

    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == 4000


def test_get_artifact_content_path_traversal_blocked(tmp_path: Path) -> None:
    """Resolved path that escapes artifact_dir -> 404 (not 200)."""
    outside = tmp_path.parent / f"secret-{tmp_path.name}.json"
    outside.write_text("leak", encoding="utf-8")

    app = _build_app(
        run_seq=[_run_row("user-1"), _artifact_row(str(outside), "user-1")],
        auth_user="user-1",
        storage=BacktestStorageConfig(artifact_dir=tmp_path),
    )

    with TestClient(app) as client:
        resp = client.get(
            "/v1/backtest-runs/run-1/artifacts/artifact-1/content",
            headers={"Authorization": _AUTH},
        )

    assert resp.status_code == 404
    outside.unlink(missing_ok=True)


def test_get_artifact_content_401_when_unauthenticated(tmp_path: Path) -> None:
    """No auth header -> 401 from the require_user dep."""
    app = _build_app(
        run_seq=[_run_row("user-1")],
        auth_user=None,
        storage=BacktestStorageConfig(artifact_dir=tmp_path),
    )

    with TestClient(app) as client:
        resp = client.get("/v1/backtest-runs/run-1/artifacts/artifact-1/content")

    assert resp.status_code == 401


def test_get_artifact_content_streams_octet_stream_for_unknown_mime(
    tmp_path: Path,
) -> None:
    """Files with no guessable extension get application/octet-stream."""
    target = tmp_path / "tear_sheet.html"
    payload = b"<html>ok</html>"
    target.write_bytes(payload)

    app = _build_app(
        run_seq=[_run_row("user-1"), _artifact_row(str(target), "user-1")],
        auth_user="user-1",
        storage=BacktestStorageConfig(artifact_dir=tmp_path),
    )

    with TestClient(app) as client:
        resp = client.get(
            "/v1/backtest-runs/run-1/artifacts/artifact-1/content",
            headers={"Authorization": _AUTH},
        )

    assert resp.status_code == 200
    assert resp.content == payload
    assert resp.headers["content-type"].startswith("text/html")
