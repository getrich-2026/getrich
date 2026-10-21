"""开发期 mock 认证开关：默认不信任 X-User-Id，无效 JWT 不回退到请求头。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from gr_api.auth import create_token
from gr_api.config import load_api_settings
from gr_api.deps import get_current_user, require_user
from gr_api.main import create_app
from gr_tools.config import Environment, SettingsError


if TYPE_CHECKING:
    from pathlib import Path


_SECRET = "mock-switch-test-secret"
_JWT_USER = "11111111-1111-1111-1111-111111111111"
_HEADER_USER = "22222222-2222-2222-2222-222222222222"
_SECURITY_HEADERS = (
    "Content-Security-Policy",
    "X-Frame-Options",
    "X-Content-Type-Options",
    "Referrer-Policy",
)


def _client(tmp_path: Path, **values: str) -> TestClient:
    """真实 create_app() 加两个探针路由；不启用 lifespan，不连接数据库。"""
    settings = load_api_settings(Environment(tmp_path, {"JWT_SECRET": _SECRET, **values}))
    app = create_app(settings)

    @app.get("/probe/optional")
    async def optional(user_id: str | None = Depends(get_current_user)):
        return {"user": user_id}

    @app.get("/probe/required")
    async def required(user_id: str = Depends(require_user)):
        return {"user": user_id}

    return TestClient(app)


def _bearer(secret: str = _SECRET, *, expires_in: int = 60) -> dict[str, str]:
    token = create_token({"sub": _JWT_USER}, secret, expires_in=expires_in)
    return {"Authorization": f"Bearer {token}"}


def test_mock_auth_defaults_off(tmp_path: Path) -> None:
    settings = load_api_settings(Environment(tmp_path, {}))
    assert settings.web.allow_mock_auth is False


@pytest.mark.parametrize("raw", ["true", "1", "yes", "on", "TRUE"])
def test_mock_auth_switch_parses_truthy_values(tmp_path: Path, raw: str) -> None:
    settings = load_api_settings(Environment(tmp_path, {"GETRICH_ALLOW_MOCK_AUTH": raw}))
    assert settings.web.allow_mock_auth is True


@pytest.mark.parametrize("app_env", ["prod", "staging", ""])
def test_mock_auth_outside_dev_refuses_to_start(tmp_path: Path, app_env: str) -> None:
    # prod 为严格模式；mock 开关须先于 PG 凭证等其余校验报错。
    env = Environment(tmp_path, {"GETRICH_ALLOW_MOCK_AUTH": "true", "APP_ENV": app_env})
    with pytest.raises(SettingsError, match="APP_ENV=dev"):
        load_api_settings(env)


def test_header_ignored_when_switch_off(tmp_path: Path) -> None:
    client = _client(tmp_path)
    headers = {"X-User-Id": _HEADER_USER}

    optional = client.get("/probe/optional", headers=headers)
    required = client.get("/probe/required", headers=headers)

    assert optional.status_code == 200
    assert optional.json()["user"] is None
    assert required.status_code == 401


def test_header_accepted_when_switch_on(tmp_path: Path) -> None:
    client = _client(tmp_path, GETRICH_ALLOW_MOCK_AUTH="true")
    headers = {"X-User-Id": _HEADER_USER}

    assert client.get("/probe/optional", headers=headers).json()["user"] == _HEADER_USER
    assert client.get("/probe/required", headers=headers).json()["user"] == _HEADER_USER


@pytest.mark.parametrize("path", ["/probe/optional", "/probe/required"])
def test_invalid_jwt_never_falls_back_to_header(tmp_path: Path, path: str) -> None:
    client = _client(tmp_path, GETRICH_ALLOW_MOCK_AUTH="true")
    for headers in (
        _bearer("wrong-secret"),
        _bearer(expires_in=-60),
        {"Authorization": "Bearer not-a-jwt"},
    ):
        response = client.get(path, headers={**headers, "X-User-Id": _HEADER_USER})
        assert response.status_code == 401, headers


def test_valid_jwt_wins_over_header(tmp_path: Path) -> None:
    client = _client(tmp_path, GETRICH_ALLOW_MOCK_AUTH="true")
    headers = {**_bearer(), "X-User-Id": _HEADER_USER}

    assert client.get("/probe/required", headers=headers).json()["user"] == _JWT_USER


def test_auth_responses_keep_security_headers(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for response in (
        client.get("/probe/optional"),
        client.get("/probe/required"),
        client.get("/probe/required", headers=_bearer()),
    ):
        for header in _SECURITY_HEADERS:
            assert header in response.headers
