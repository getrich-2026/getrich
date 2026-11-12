"""Batch 1：鉴权、启动门禁、行业展示及报告裁剪回归。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from gr_api.auth import create_token
from gr_api.config import load_api_settings
from gr_api.deps import get_db
from gr_api.diagnosis_calc.exposure import CalcHolding, IndustryAssignment, compute_exposure
from gr_api.errors import Forbidden
from gr_api.main import create_app
from gr_api.schemas.diagnosis_response import ExposureMetrics
from gr_api.services import diagnosis as svc
from gr_tools.config import Environment, SettingsError


HEADERS = (
    "Content-Security-Policy",
    "X-Frame-Options",
    "X-Content-Type-Options",
    "Referrer-Policy",
)
SID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = load_api_settings(Environment(tmp_path, {"JWT_SECRET": "fixture-key"}))
    app = create_app(settings)

    async def forbidden_db():
        raise AssertionError("anonymous requests must not acquire a database connection")
        yield  # pragma: no cover

    app.dependency_overrides[get_db] = forbidden_db
    return TestClient(app)


@pytest.mark.parametrize("token", [None, "invalid", "expired"])
def test_all_private_routes_require_login(client: TestClient, token: str | None) -> None:
    headers = {}
    if token is not None:
        raw = (
            create_token({"sub": SID}, "fixture-key", expires_in=-60)
            if token == "expired"
            else token
        )
        headers["Authorization"] = f"Bearer {raw}"
    paths = client.app.openapi()["paths"]  # type: ignore[attr-defined]
    for path, methods in paths.items():
        if not path.startswith("/v1/diagnosis/") or path == "/v1/diagnosis/share/{token}/report":
            continue
        concrete = path.replace("{snapshot_id}", SID)
        for method, operation in methods.items():
            if method not in ("get", "post"):
                continue
            assert "401" in operation["responses"]
            response = client.request(method, concrete, headers=headers, json={})
            assert response.status_code == 401, (path, response.text)
            assert response.json()["error"]["code"] == "unauthorized"
            assert response.json()["request_id"]
            assert all(header in response.headers for header in HEADERS)


def test_public_share_does_not_require_login(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def db():
        yield object()

    client.app.dependency_overrides[get_db] = db  # type: ignore[attr-defined]
    monkeypatch.setattr(
        svc, "get_shared_report", AsyncMock(side_effect=Forbidden("share unavailable"))
    )
    response = client.get("/v1/diagnosis/share/sample/report")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_other_users_read_is_forbidden(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def db():
        yield object()

    client.app.dependency_overrides[get_db] = db  # type: ignore[attr-defined]
    monkeypatch.setattr(svc, "get_result", AsyncMock(side_effect=Forbidden("not the owner")))
    token = create_token({"sub": SID}, "fixture-key", expires_in=60)
    response = client.get(
        f"/v1/diagnosis/snapshots/{SID}/result", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert all(header in response.headers for header in HEADERS)


@pytest.mark.parametrize("app_env", ["staging", "prod"])
@pytest.mark.parametrize(
    "updates,match",
    [
        ({"JWT_SECRET": ""}, "JWT_SECRET"),
        ({"JWT_SECRET": "getrich-dev-secret-change-in-prod"}, "JWT_SECRET"),
        ({"WEB_CORS_ORIGINS": ""}, "WEB_CORS_ORIGINS"),
        ({"WEB_CORS_ORIGINS": "*"}, "WEB_CORS_ORIGINS"),
    ],
)
def test_non_dev_security_settings(
    tmp_path: Path, app_env: str, updates: dict[str, str], match: str
) -> None:
    values = {
        "APP_ENV": app_env,
        "JWT_SECRET": "fixture-key",
        "WEB_CORS_ORIGINS": "http://localhost:3000",
        **updates,
    }
    with pytest.raises(SettingsError, match=match):
        load_api_settings(Environment(tmp_path, values))


def test_missing_non_dev_security_settings(tmp_path: Path) -> None:
    with pytest.raises(SettingsError, match="JWT_SECRET"):
        load_api_settings(Environment(tmp_path, {"APP_ENV": "staging"}))
    with pytest.raises(SettingsError, match="WEB_CORS_ORIGINS"):
        load_api_settings(
            Environment(tmp_path, {"APP_ENV": "staging", "JWT_SECRET": "fixture-key"})
        )


def test_empty_payment_secret_rejects_before_processing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gr_api.services import payment

    handler = AsyncMock()
    monkeypatch.setattr(payment, "handle_webhook", handler)
    response = client.post("/v1/webhooks/payment", content=b"{}")
    assert response.status_code == 503
    handler.assert_not_awaited()
    assert all(header in response.headers for header in HEADERS)


@pytest.mark.parametrize("scheme", [None, "sw2021"])
def test_industry_labels_and_per_stock_assignment(scheme: str | None) -> None:
    metrics, _ = compute_exposure(
        [CalcHolding(1, Decimal("0.6")), CalcHolding(2, Decimal("0.4"))],
        as_of=date(2026, 11, 5),
        params={},
        industry_scheme=scheme,
        industry={1: IndustryAssignment("801780", "银行")},
        category={},
        valuation={},
    )
    validated = ExposureMetrics.model_validate(metrics).model_dump()
    assert validated["industry_labels"] == ({"801780": "银行"} if scheme else {})
    facts = metrics["instrument_facts"]["value"]
    assert facts["1"]["industry_name"] == ("银行" if scheme else None)
    assert facts["1"]["industry_code"] == ("801780" if scheme else None)
    assert facts["2"]["industry_code"] is None
    assert facts["2"]["industry_name"] is None


def test_staging_config_accepts_explicit_origins(tmp_path: Path) -> None:
    settings = load_api_settings(
        Environment(
            tmp_path,
            {
                "APP_ENV": "staging",
                "JWT_SECRET": "fixture-key",
                "WEB_CORS_ORIGINS": "http://localhost:3000,http://127.0.0.1:3000",
            },
        )
    )
    app = create_app(settings)
    response = TestClient(app).options(
        "/v1/diagnosis/options",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
