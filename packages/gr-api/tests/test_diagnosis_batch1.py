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
            assert response.json()["request_id"] == response.headers["X-Request-Id"]
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


@pytest.mark.parametrize("app_env", [" STAGING ", " Dev ", "prod", "unknown", ""])
def test_environment_normalization(tmp_path: Path, app_env: str) -> None:
    values = {
        "APP_ENV": app_env,
        "PG_PASSWORD": "fixture-password",
        "BACKTEST_ARTIFACT_DIR": str(tmp_path),
        "JWT_SECRET": "fixture-secret",
        "WEB_CORS_ORIGINS": "https://api.example",
    }
    if app_env in ("unknown", ""):
        with pytest.raises(SettingsError, match="APP_ENV"):
            load_api_settings(Environment(tmp_path, values))
    else:
        assert load_api_settings(Environment(tmp_path, values)).env == app_env.strip().lower()


@pytest.mark.parametrize("secret", ["change-me-local-only", " Change-Me-production "])
def test_template_jwt_refused(tmp_path: Path, secret: str) -> None:
    with pytest.raises(SettingsError, match="JWT_SECRET"):
        load_api_settings(Environment(tmp_path, {"APP_ENV": "staging", "JWT_SECRET": secret}))


def test_prod_rejects_local_only_cors(tmp_path: Path) -> None:
    with pytest.raises(SettingsError, match="local origins"):
        load_api_settings(
            Environment(
                tmp_path,
                {
                    "APP_ENV": "prod",
                    "JWT_SECRET": "fixture-secret",
                    "WEB_CORS_ORIGINS": "http://localhost:3000,http://127.0.0.1:3000",
                },
            )
        )


@pytest.mark.parametrize("origin", ["localhost:3000", "http://", "file:///tmp/test"])
def test_staging_refuses_malformed_origins(tmp_path: Path, origin: str) -> None:
    with pytest.raises(SettingsError, match="hostname"):
        load_api_settings(
            Environment(
                tmp_path,
                {"APP_ENV": "staging", "JWT_SECRET": "fixture-secret", "WEB_CORS_ORIGINS": origin},
            )
        )


def test_prod_refuses_mixed_local_origins(tmp_path: Path) -> None:
    with pytest.raises(SettingsError, match="local origins"):
        load_api_settings(
            Environment(
                tmp_path,
                {
                    "APP_ENV": "prod",
                    "JWT_SECRET": "fixture-secret",
                    "WEB_CORS_ORIGINS": "https://api.example,http://[::1]:3000",
                },
            )
        )


def test_success_request_id_matches_header(client: TestClient) -> None:
    from fastapi import Depends
    from gr_api.deps import request_id

    @client.app.get("/request-id-probe")  # type: ignore[attr-defined]
    async def probe(rid: str = Depends(request_id)):
        return {"request_id": rid}

    response = client.get("/request-id-probe")
    assert response.status_code == 200
    assert response.json()["request_id"] == response.headers["X-Request-Id"]


def test_public_share_report_200_allowlist_strips_private_blocks_and_symbols(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """有效分享 token 返回 HTTP 200 + 安全响应头，保留组合级统计/披露，严格剥离逐股与私有块。"""
    import json

    async def db():
        yield object()

    client.app.dependency_overrides[get_db] = db  # type: ignore[attr-defined]
    fake_report = {
        "report_mode": "standard",
        "run_status": "partially_succeeded",
        "disclosures": ["本报告基于快照计算，不构成投资建议。"],
        "sections": [
            {
                "section_id": "p1:instrument",
                "plan_id": "p1",
                "kind": "instrument",
                "title": "输入持仓与解析结果",
                "content": {
                    "status": "ready",
                    "value": [
                        {
                            "type": "holdings",
                            "input": {
                                "holdings": [{"input_symbol": "600519.SH", "input_weight": "60"}]
                            },
                        }
                    ],
                },
            },
            {
                "section_id": "p1:exposure",
                "plan_id": "p1",
                "kind": "exposure",
                "title": "构成与敞口",
                "content": {
                    "status": "ready",
                    "value": [
                        {
                            "type": "metric_cards",
                            "items": [
                                {
                                    "metric_id": "top1",
                                    "label": "Top1 权重",
                                    "value": {"status": "ok", "value": 0.6, "method": "exposure"},
                                    "format": "percent",
                                    "decimals": 1,
                                }
                            ],
                        },
                        {
                            "type": "distribution",
                            "metric_id": "industry_distribution",
                            "labels": {"801120.SI": "食品饮料"},
                            "values": {
                                "status": "ok",
                                "value": {"801120.SI": 1.0},
                                "method": "exposure",
                            },
                        },
                    ],
                },
            },
            {
                "section_id": "p1:risk",
                "plan_id": "p1",
                "kind": "risk",
                "title": "风险画像",
                "content": {
                    "status": "ready",
                    "value": [
                        {
                            "type": "holding_risk_comparison",
                            "headline": "秘密股票（600519.SH）占资金 60.0%。",
                            "stocks": {
                                "status": "unavailable",
                                "reason_code": "not_applicable",
                                "reason": "x",
                            },
                            "industries": {
                                "status": "unavailable",
                                "reason_code": "not_applicable",
                                "reason": "x",
                            },
                        },
                        {
                            "type": "metric_cards",
                            "items": [
                                {
                                    "metric_id": "volatility.forward",
                                    "label": "模型年化波动率",
                                    "value": {"status": "ok", "value": 0.21, "method": "forward"},
                                    "format": "percent",
                                    "decimals": 1,
                                },
                                {
                                    "metric_id": "l4_largest_source",
                                    "label": "最大风险源占比（秘密股票 的特质风险）",
                                    "value": {"status": "ok", "value": 0.45, "method": "forward"},
                                    "format": "percent",
                                    "decimals": 1,
                                },
                                {
                                    "metric_id": "risk_contribution_ratio:101",
                                    "label": "秘密股票 风险贡献占比",
                                    "value": {"status": "ok", "value": 0.72, "method": "forward"},
                                    "format": "percent",
                                    "decimals": 1,
                                },
                            ],
                        },
                        {"type": "text", "text": "600519.SH，权重 0.6：因子暴露缺失"},
                        {
                            "type": "text",
                            "text": (
                                "L4 描述模型下互不相关的风险源之间的方差集中度，"
                                "数值越大不代表越分散。"
                            ),
                        },
                    ],
                },
            },
            {
                "section_id": "limitations",
                "plan_id": None,
                "kind": "limitations",
                "title": "方法与数据局限",
                "content": {
                    "status": "ready",
                    "value": [{"type": "text", "text": "本报告基于快照计算，不构成投资建议。"}],
                },
            },
        ],
    }
    monkeypatch.setattr(svc, "get_shared_report", AsyncMock(return_value=fake_report))

    response = client.get("/v1/diagnosis/share/valid-token/report")
    assert response.status_code == 200
    assert all(header in response.headers for header in HEADERS)
    body = response.json()["data"]
    assert body["report_mode"] == "standard"
    assert body["disclosures"] == ["本报告基于快照计算，不构成投资建议。"]

    raw_json = json.dumps(body, ensure_ascii=False)
    for forbidden in (
        "600519.SH",
        "秘密股票",
        "holding_risk_comparison",
        "risk_contribution_ratio:101",
        "input_weight",
        "/holdings/",
    ):
        assert forbidden not in raw_json

    risk_sec = next(s for s in body["sections"] if s["title"] == "风险画像")
    cards_block = next(b for b in risk_sec["content"]["value"] if b["type"] == "metric_cards")
    card_ids = {item["metric_id"]: item["label"] for item in cards_block["items"]}
    assert card_ids == {
        "volatility.forward": "模型年化波动率",
        "l4_largest_source": "最大风险源占比（单一持仓特质风险）",
    }


def test_public_share_report_sanitizes_truncated_replay_instrument_id(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """真实语义的回放截断报告经分享投影后保留中止日期与原因，但绝不泄露受影响标的 ID。"""
    import json
    from datetime import date
    from decimal import Decimal

    from gr_api.diagnosis_calc.replay import ReplayPoint, ReplayResult
    from gr_api.diagnosis_calc.replay_section import history_section
    from gr_api.services import diagnosis_presentation as view

    async def db():
        yield object()

    client.app.dependency_overrides[get_db] = db  # type: ignore[attr-defined]
    points = (
        ReplayPoint(date(2025, 3, 19), Decimal("1.00"), Decimal("1.00"), Decimal("0")),
        ReplayPoint(date(2025, 3, 20), Decimal("0.97"), Decimal("0.97"), Decimal("0")),
    )
    sec_c = history_section(
        ReplayResult(
            points=points,
            stopped_on=date(2025, 3, 21),
            reason="delisted_no_terminal_value",
            instrument_id=33582,
        ),
        window=(date(2025, 3, 19), date(2025, 3, 24)),
        benchmark_returns={},
    )
    values = sec_c["value"]
    history_cards = [
        view._card(key, label, values[key], fmt, 2)
        for key, label, fmt in (
            ("replay_volatility", "历史回放年化波动率", "percent"),
            ("portfolio_beta", "组合 Beta", "number"),
            ("portfolio_benchmark_correlation", "与基准的相关性", "number"),
            ("current_drawdown", "当前回撤", "percent"),
            ("var", "历史回放单日 VaR（95%）", "percent"),
            ("cvar", "历史回放单日 CVaR（95%）", "percent"),
            ("max_drawdown", "最大回撤", "percent"),
        )
    ]
    private_report = {
        "report_mode": "standard",
        "run_status": "partially_succeeded",
        "disclosures": ["本报告基于快照计算，不构成投资建议。"],
        "sections": [
            {
                "section_id": "p1:history",
                "plan_id": "p1",
                "kind": "style",
                "title": "历史回放与分位",
                "content": {
                    "status": "ready",
                    "value": [
                        {
                            "type": "replay_chart",
                            "values": values["replay"],
                            "stats_window": {"start": "2025-03-19", "end": "2025-03-24"},
                        },
                        {"type": "metric_cards", "items": history_cards},
                    ],
                },
            },
            {
                "section_id": "limitations",
                "plan_id": None,
                "kind": "limitations",
                "title": "方法与数据局限",
                "content": {
                    "status": "ready",
                    "value": [{"type": "text", "text": "本报告基于快照计算，不构成投资建议。"}],
                },
            },
        ],
    }
    # 私有报告中原始原因含受影响标的 33582
    assert "33582" in json.dumps(private_report, ensure_ascii=False, default=str)

    monkeypatch.setattr(svc, "get_shared_report", AsyncMock(return_value=private_report))
    response = client.get("/v1/diagnosis/share/truncated-token/report")
    assert response.status_code == 200
    assert all(header in response.headers for header in HEADERS)

    body = response.json()["data"]
    raw_json = json.dumps(body, ensure_ascii=False)
    assert "33582" not in raw_json
    assert "replay_chart" not in raw_json

    history_sec = next(s for s in body["sections"] if s["title"] == "历史回放与分位")
    cards_block = next(b for b in history_sec["content"]["value"] if b["type"] == "metric_cards")
    mdd = next(c for c in cards_block["items"] if c["metric_id"] == "max_drawdown")
    assert mdd["value"]["status"] == "unavailable"
    assert mdd["value"]["reason_code"] == "replay_terminated"
    assert "2025-03-21" in mdd["value"]["reason"]
    assert "退市" in mdd["value"]["reason"]
