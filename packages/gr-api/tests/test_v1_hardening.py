"""V1 上线加固回归测试：禁用账号拦截、最小路由面开关、回测鉴权与网格上限、错误响应脱敏。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import gr_api.main as main_module
import pytest
from fastapi.testclient import TestClient
from gr_api.auth import create_token
from gr_api.config import ApiSettings, load_api_settings
from gr_api.deps import get_db
from gr_api.errors import BadRequest
from gr_api.main import create_app
from gr_api.schemas.backtest import MAX_GRID_COMBINATIONS, SweepRunRequest, WalkForwardRunRequest
from gr_api.services import backtest_job
from gr_tools.config import Environment, SettingsError
from pydantic import ValidationError


_TZ = ZoneInfo("Asia/Shanghai")
_SECURITY_HEADERS = (
    "Content-Security-Policy",
    "X-Frame-Options",
    "X-Content-Type-Options",
    "Referrer-Policy",
)


def _assert_security_headers(headers: Any) -> None:
    for name in _SECURITY_HEADERS:
        assert headers.get(name), f"missing security header: {name}"


def _prod_like_settings(
    tmp_path: Path, *, env_name: str = "prod", v1_only: bool = False
) -> ApiSettings:
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    environment = Environment(
        tmp_path,
        {
            "APP_ENV": env_name,
            "STRICT_MODE": "true",
            "PG_PASSWORD": "fixture-pg-password",
            "JWT_SECRET": "fixture-prod-jwt-secret-32-chars-ok",
            "WEB_CORS_ORIGINS": "https://app.example.com",
            "BACKTEST_ARTIFACT_DIR": str(artifact_dir),
            "GETRICH_V1_DIAGNOSIS_ONLY": "true" if v1_only else "false",
        },
    )
    return load_api_settings(environment)


class _AuthGuardCursor:
    """模拟 user_auth 存在密码哈希但关联账号 is_active=FALSE 的数据库游标。"""

    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, Any] | None]] = []

    async def __aenter__(self) -> _AuthGuardCursor:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, sql: str, params: dict[str, Any] | None = None) -> None:
        self.executed.append((sql, params))

    async def fetchone(self) -> dict[str, Any] | None:
        sql, _ = self.executed[-1]
        lowered = sql.lower()
        # 若 SQL 漏写 is_active = true 过滤条件，则返回假行使测试立即失败，防止回归。
        if "from app.user_auth" in lowered and "u.is_active = true" not in lowered:
            return {
                "user_id": "disabled-user-1",
                "credential": "$2b$12$c3lZxMMPPPn40Pg104gng.47ED584SS/eWbayiO7NoBLKtjKXUamK",
                "name": "Disabled User",
            }
        return None


class _AuthGuardConn:
    def __init__(self, cursor: _AuthGuardCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _AuthGuardCursor:
        return self._cursor

    async def commit(self) -> None:
        return None


def test_disabled_user_rejected_on_login_via_user_auth_path1(tmp_path: Path) -> None:
    """禁用用户在 Path 1 (app.user_auth) 登录时必须要求 u.is_active = TRUE 并返回 401。"""
    settings = _prod_like_settings(tmp_path, v1_only=True)
    app = create_app(settings)
    cursor = _AuthGuardCursor()
    app.dependency_overrides[get_db] = lambda: _AuthGuardConn(cursor)

    client = TestClient(app)
    resp = client.post(
        "/v1/auth/login",
        json={"email": "disabled@example.com", "password": "password"},
    )
    assert resp.status_code == 401
    _assert_security_headers(resp.headers)
    assert resp.json()["code"] != 0
    assert len(cursor.executed) == 2
    assert "from app.user_auth" in cursor.executed[0][0].lower()
    assert "u.is_active = true" in cursor.executed[0][0].lower()
    assert "from app.users" in cursor.executed[1][0].lower()


def test_v1_diagnosis_only_locks_down_routes_and_skips_listener(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GETRICH_V1_DIAGNOSIS_ONLY=true 仅暴露 auth/user/diagnosis/health/metrics 并跳过监听器。"""
    bad_env = Environment(tmp_path, {"GETRICH_V1_DIAGNOSIS_ONLY": "not-a-bool"})
    with pytest.raises(SettingsError, match="GETRICH_V1_DIAGNOSIS_ONLY"):
        load_api_settings(bad_env)

    settings = _prod_like_settings(tmp_path, v1_only=True)
    assert settings.web.v1_diagnosis_only is True

    monkeypatch.setattr(main_module.pg_pool, "init", AsyncMock())
    monkeypatch.setattr(main_module.pg_pool, "close", AsyncMock())
    listener_calls: list[Any] = []

    def _unexpected_listener(cfg: Any) -> Any:
        listener_calls.append(cfg)
        return SimpleNamespace(start=AsyncMock(), stop=AsyncMock(), is_holder=False)

    monkeypatch.setattr(main_module, "BacktestJobListener", _unexpected_listener)
    app = create_app(settings)

    route_paths = set(app.openapi()["paths"])
    assert "/v1/auth/login" in route_paths
    assert "/v1/user/orders" in route_paths
    assert "/v1/diagnosis/options" in route_paths
    assert "/v1/diagnosis/snapshots" in route_paths
    assert "/health" in route_paths
    assert "/metrics" in route_paths
    assert "/v1/backtest-jobs/backtest" not in route_paths
    assert "/v1/admin/imports/history" not in route_paths
    assert "/v1/strategies" not in route_paths

    with TestClient(app) as client:
        assert listener_calls == []

        health_resp = client.get("/health")
        assert health_resp.status_code == 200
        _assert_security_headers(health_resp.headers)

        metrics_resp = client.get("/metrics")
        assert metrics_resp.status_code == 200
        _assert_security_headers(metrics_resp.headers)

        user_resp = client.get("/v1/user/orders")
        assert user_resp.status_code == 401
        _assert_security_headers(user_resp.headers)

        diag_resp = client.post("/v1/diagnosis/snapshots", json={"plans": []})
        assert diag_resp.status_code == 401
        _assert_security_headers(diag_resp.headers)

        bt_resp = client.post("/v1/backtest-jobs/backtest", json={})
        assert bt_resp.status_code == 404
        _assert_security_headers(bt_resp.headers)

        admin_resp = client.get("/v1/admin/imports/history")
        assert admin_resp.status_code == 404
        _assert_security_headers(admin_resp.headers)


def test_non_dev_backtest_requires_auth_and_caps_grid_combinations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """非 dev 环境匿名触发回测返回 401；超大网格参数扫描返回 422。"""
    settings = _prod_like_settings(tmp_path, env_name="staging", v1_only=False)
    app = create_app(settings)
    app.dependency_overrides[get_db] = lambda: object()
    monkeypatch.setattr(
        backtest_job,
        "create_backtest_job",
        AsyncMock(return_value=("job-1", "run-1")),
    )
    monkeypatch.setattr(backtest_job, "run_job_synchronously", AsyncMock())

    base_payload: dict[str, Any] = {
        "strategy_name": "macross",
        "symbols": ["000001.SZ"],
        "start": datetime(2026, 6, 1, 9, 30, tzinfo=_TZ).isoformat(),
        "end": datetime(2026, 6, 2, 9, 30, tzinfo=_TZ).isoformat(),
        "initial_cash": "100000",
    }

    client = TestClient(app)
    anon_resp = client.post("/v1/backtest-jobs/backtest", json=base_payload)
    assert anon_resp.status_code == 401
    _assert_security_headers(anon_resp.headers)

    token = create_token({"sub": "user-1"}, settings.web.jwt_secret, expires_in=300)
    auth_headers = {"Authorization": f"Bearer {token}"}
    authed_resp = client.post("/v1/backtest-jobs/backtest", json=base_payload, headers=auth_headers)
    assert authed_resp.status_code == 202
    _assert_security_headers(authed_resp.headers)

    oversized_sweep = {
        **base_payload,
        "search_spec": {
            "space": {
                "fast": list(range(40)),
                "slow": list(range(30)),
            }
        },
    }
    sweep_resp = client.post("/v1/backtest-jobs/sweep", json=oversized_sweep, headers=auth_headers)
    assert sweep_resp.status_code == 422
    _assert_security_headers(sweep_resp.headers)
    assert str(MAX_GRID_COMBINATIONS) in sweep_resp.json()["message"]

    with pytest.raises(ValidationError, match=str(MAX_GRID_COMBINATIONS)):
        SweepRunRequest.model_validate(
            {
                **base_payload,
                "search_spec": {"space": {"fast": {"kind": "int_range", "values": [1, 2, 5000]}}},
            }
        )

    with pytest.raises(ValidationError, match=str(MAX_GRID_COMBINATIONS)):
        WalkForwardRunRequest.model_validate(
            {
                **base_payload,
                "train_months": 6,
                "val_months": 2,
                "search_spec": {
                    "space": {"th": {"kind": "decimal_range", "values": ["0.001", "0.002", "2.0"]}}
                },
            }
        )


def test_error_request_id_matches_header_and_prod_500_hides_exception(
    tmp_path: Path,
) -> None:
    """错误响应 JSON 的 request_id 与 X-Request-Id 头一致，且非 dev 500 隐藏内部异常文本。"""
    prod_settings = _prod_like_settings(tmp_path, env_name="prod", v1_only=True)
    prod_app = create_app(prod_settings)

    @prod_app.get("/test-api-error")
    async def raise_api_error() -> None:
        raise BadRequest("bad input detail")

    @prod_app.get("/test-unexpected")
    async def raise_unexpected() -> None:
        raise RuntimeError("sensitive-sql-fragment-do-not-leak")

    prod_client = TestClient(prod_app, raise_server_exceptions=False)

    err_400 = prod_client.get("/test-api-error")
    assert err_400.status_code == 400
    _assert_security_headers(err_400.headers)
    assert err_400.json()["request_id"] == err_400.headers["X-Request-Id"]
    assert err_400.json()["request_id"] != "-"

    err_500 = prod_client.get("/test-unexpected")
    assert err_500.status_code == 500
    _assert_security_headers(err_500.headers)
    body_500 = err_500.json()
    assert body_500["request_id"] == err_500.headers["X-Request-Id"]
    assert body_500["message"] == "internal server error"
    assert "sensitive-sql-fragment-do-not-leak" not in err_500.text

    dev_settings = replace(prod_settings, env="dev")
    dev_app = create_app(dev_settings)

    @dev_app.get("/test-unexpected")
    async def raise_unexpected_dev() -> None:
        raise RuntimeError("dev-visible-detail")

    dev_client = TestClient(dev_app, raise_server_exceptions=False)
    dev_500 = dev_client.get("/test-unexpected")
    assert dev_500.status_code == 500
    _assert_security_headers(dev_500.headers)
    assert dev_500.json()["request_id"] == dev_500.headers["X-Request-Id"]
    assert "dev-visible-detail" in dev_500.json()["message"]
