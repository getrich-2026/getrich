"""前端契约回归：区块状态、请求隔离、有限数、报告及 HTTP/SSE 一致性。"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gr_api.deps import get_current_user, get_db
from gr_api.routers.diagnosis import _stream_sections, router
from gr_api.schemas.diagnosis import SnapshotRequest
from gr_api.schemas.diagnosis_response import (
    CorrelationMatrix,
    DiagnosisResult,
    MetricValue,
    ReportResponse,
    SectionResult,
)
from gr_api.services import diagnosis as svc, diagnosis_presentation as view
from pydantic import FiniteFloat, ValidationError


def fixture_result(*, coverage: float = 1.0, failed: bool = False) -> tuple[dict, dict]:
    holdings = [{"instrument_id": 1, "symbol": "600000.SH", "name": "浦发银行", "weight": 1.0}]
    a = svc._build_exposure_section(
        holdings,
        params={},
        industry={1: "Banks"},
        category={1: {"market": "CN", "asset_category": "equity"}},
        valuation={},
        has_fund=False,
        input_weight=Decimal(1),
        resolved_weight=Decimal(1),
    )
    payload = {
        "section_a": a,
        "section_b": None,
        "section_c": None,
        "section_d": None,
        "blindspots": [],
        "profile": svc._build_profile(a, holdings),
        "weight_mode": "user",
    }
    requested = [{"symbol": "600000.SH", "weight": str(coverage)}]
    if coverage < 1:
        requested.append({"symbol": "UNKNOWN", "weight": str(1 - coverage)})
    row = {
        "plan_index": 0,
        "plan_id": "mine",
        "label": "我的方案",
        "weight_mode": "user",
        "requested_holdings": requested,
        "resolved_holdings": holdings,
        "status": "failed" if failed else "succeeded",
        "payload": None if failed else payload,
        "data_quality": {
            "coverage_summary": {"industry": 1.0},
            "forced_disclosures": ["只分析当前持仓构成"],
        },
        "data_fingerprint": "fixture",
        "data_snapshot_at": datetime(2026, 9, 1, 18, tzinfo=ZoneInfo("Asia/Shanghai")),
    }
    context = svc._request_context_from_plan_row(row)
    old = svc._assemble_plan_result(row, context)
    snapshot = {
        "snapshot_id": uuid4(),
        "resolved_spec_version": "fixture-v1",
        "resolved_as_of_date": date(2026, 9, 1),
        "resolved_intent": "single_portfolio",
    }
    result = view.assemble(
        snapshot,
        {"params": {}},
        [row],
        [context],
        [old] if old else [],
        [svc._assemble_plan_data_quality(row, context)],
        row["status"],
    )
    return result, payload


def test_all_sections_have_explicit_states_and_input_echo() -> None:
    result, _ = fixture_result()
    DiagnosisResult.model_validate(result)
    plan = result["plans"][0]
    assert plan["section_a"]["value"]["hhi"]["value"] == 1
    assert plan["input"]["holdings"][0]["name"] == "浦发银行"
    assert plan["input"]["calculation_holdings"][0]["calculation_weight"] == 1
    assert plan["section_b"] == view.unavailable("feature_not_available", "风险计算尚未开放。")
    assert plan["section_c"]["reason_code"] == "spec_not_defined"
    assert result["comparison"]["reason_code"] == "not_applicable"
    assert plan["cov"] == {"requested": ["historical"], "primary": None, "computed": []}
    assert all(plan[key] is not None for key in view.SECTION_IDS)


def test_missing_input_changes_metrics_and_profile_without_mutating_cache() -> None:
    result, payload = fixture_result(coverage=0.5)
    plan = result["plans"][0]
    assert plan["input"]["resolved_weight"] == 0.5
    assert plan["section_a"]["value"]["hhi"]["status"] == "unavailable"
    assert "value" not in plan["section_a"]["value"]["hhi"]
    assert plan["profile"]["value"]["label"] == "数据不足"
    assert payload["section_a"]["hhi"]["status"] == "ok"
    assert any(i["paths"] == ["/holdings/1"] for i in result["data_quality"]["plans"][0]["issues"])
    assert all(b["status"] == "unavailable" for b in plan["blindspots"]["value"])


def test_degraded_coverage_remains_visible_in_both_report_levels() -> None:
    result, _ = fixture_result(coverage=0.9)
    assert result["plans"][0]["section_a"]["value"]["hhi"]["status"] == "degraded"
    for level in ("retail", "pro"):
        report = view.report(result, level)
        ReportResponse.model_validate(report)
        assert report["disclosures"] == result["disclosures"]
        assert report["data_quality"] == result["data_quality"]
        sections = {s["section_id"]: s for s in report["sections"]}
        assert sections["mine:risk"]["content"]["reason_code"] == "feature_not_available"
        assert sections["mine:instrument"]["content"]["value"][0]["input"][
            "unresolved_weight"
        ] == pytest.approx(0.1)
        cards = sections["mine:exposure"]["content"]["value"][0]["items"]
        assert any(c["value"]["status"] == "degraded" for c in cards)
        assert all(isinstance(c["value"]["value"], (int, float)) for c in cards)


def test_failed_plan_is_preserved_with_safe_error_and_input() -> None:
    result, _ = fixture_result(failed=True)
    assert result["run_status"] == "failed"
    plan = result["plans"][0]
    assert plan["plan_id"] == "mine"
    assert plan["error"]["retryable"]
    assert all(plan[key]["status"] == "failed" for key in view.SECTION_IDS)
    ReportResponse.model_validate(view.report(result))


@pytest.mark.parametrize(
    "body",
    [
        {"plans": [{"plan_id": "p", "holdings": [{"symbol": " "}]}]},
        {"plans": [{"plan_id": "p", "holdings": [{"symbol": "A"}]}] * 2},
        {"plans": [{"plan_id": "p", "holdings": [{"symbol": "A"}]}], "intent": "rebalance_amount"},
        {"plans": [{"plan_id": "p", "holdings": [{"symbol": "A"}]}], "user_level": "pro"},
        {"plans": [{"plan_id": "p", "holdings": [{"symbol": "A", "weight": "NaN"}]}]},
    ],
)
def test_requests_reject_ambiguous_or_nonfinite_input(body: dict) -> None:
    with pytest.raises(ValidationError):
        SnapshotRequest.model_validate(body)


@pytest.mark.parametrize("value", [None, float("nan"), float("inf")])
def test_finite_metric_rejects_invalid_value(value: float | None) -> None:
    with pytest.raises(ValidationError):
        MetricValue[FiniteFloat].model_validate({"status": "ok", "method": "exact", "value": value})


def test_unavailable_cannot_carry_a_number_or_null_section() -> None:
    with pytest.raises(ValidationError):
        MetricValue[FiniteFloat].model_validate(
            {**view.unavailable("spec_not_defined", "未定"), "value": 0}
        )
    with pytest.raises(ValidationError):
        SectionResult[FiniteFloat].model_validate(None)


@pytest.mark.anyio
async def test_late_sse_complete_is_exact_result() -> None:
    result, _ = fixture_result()

    class Connected:
        async def is_disconnected(self) -> bool:
            return False

    frames = [f async for f in _stream_sections(UUID(result["snapshot_id"]), result, Connected())]
    assert len(frames) == 2
    assert b"event: meta" in frames[0]
    assert b"event: complete" in frames[1]
    complete = next(
        line[6:] for line in frames[1].decode().splitlines() if line.startswith("data: ")
    )
    assert json.loads(complete) == result


def test_normalization_keeps_zero_out_and_quantized_sum_exact() -> None:
    request = SnapshotRequest.model_validate(
        {
            "plans": [
                {
                    "plan_id": "p",
                    "holdings": [
                        {"symbol": "600000.SH", "weight": 1},
                        {"symbol": "000001.SZ", "weight": 0},
                    ],
                }
            ]
        }
    )
    resolved = {
        s: {"instrument_id": i, "symbol": s} for i, s in enumerate(("600000.SH", "000001.SZ"), 1)
    }
    holdings = svc._normalize_plan(request.plans[0], resolved)[1]
    assert len(holdings) == 1
    assert holdings[0]["weight"] == 1.0


def test_matrix_rejects_wrong_dimensions() -> None:
    with pytest.raises(ValidationError):
        CorrelationMatrix(instrument_ids=[1, 2], matrix=[[1]])


@pytest.fixture
def api_client(monkeypatch: pytest.MonkeyPatch):
    from gr_api.middleware import SecurityHeadersMiddleware

    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, csp_policy="default-src 'none'")
    app.include_router(router, prefix="/v1")

    async def db():
        yield object()

    async def user():
        return None

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_current_user] = user
    result, _ = fixture_result()

    async def get_result(*args, **kwargs):
        return deepcopy(result)

    async def create(*args, **kwargs):
        return view.accepted(result), 201

    async def report(*args, **kwargs):
        return view.report(result, kwargs.get("user_level") or "retail")

    monkeypatch.setattr(svc, "get_result", get_result)
    monkeypatch.setattr(svc, "create_snapshot", create)
    monkeypatch.setattr(svc, "get_report", report)
    with TestClient(app) as client:
        yield client, result


def test_http_contract_links_headers_and_report(api_client) -> None:
    client, result = api_client
    response = client.post(
        "/v1/diagnosis/snapshots",
        json={"plans": [{"plan_id": "p", "holdings": [{"symbol": "600000.SH"}]}]},
    )
    assert response.status_code == 201
    links = response.json()["data"]["links"]
    assert response.headers["location"] == links["result"]
    assert client.get(links["result"]).json()["data"] == result
    report = client.get(links["report"], params={"user_level": "pro"})
    assert report.status_code == 200
    assert report.json()["data"]["user_level"] == "pro"
    assert report.headers["cache-control"] == "private, no-store"
    for name in (
        "content-security-policy",
        "x-frame-options",
        "x-content-type-options",
        "referrer-policy",
    ):
        assert name in report.headers


def test_http_validation_is_structured_without_input_leak(api_client) -> None:
    client, _ = api_client
    response = client.post("/v1/diagnosis/snapshots", json={"plans": []})
    assert response.status_code == 422
    assert response.json()["error"]["issues"][0]["path"] == "/plans"
    response = client.post(
        "/v1/diagnosis/snapshots",
        headers={"Idempotency-Key": "invalid"},
        json={"plans": [{"plan_id": "p", "holdings": [{"symbol": "600000.SH"}]}]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["issues"][0]["path"] == "/headers/Idempotency-Key"


def test_openapi_exposes_sections_and_success_statuses(api_client) -> None:
    client, _ = api_client
    schema = client.get("/openapi.json").json()
    submit = schema["paths"]["/v1/diagnosis/snapshots"]["post"]
    assert {"200", "201", "202", "422", "409"} <= submit["responses"].keys()
    assert any(p["name"] == "Idempotency-Key" for p in submit["parameters"])
    assert "user_level" not in schema["components"]["schemas"]["SnapshotRequest"]["properties"]
    # Pydantic 可按输入/输出模式拆分组件名称，断言实际模型而非自动生成的键名。
    results = [
        model
        for model in schema["components"]["schemas"].values()
        if model.get("title") == "DiagnosisResult"
    ]
    assert results and all("comparison" in model["properties"] for model in results)


def test_pending_result_report_and_quality_share_progress_contract(api_client, monkeypatch) -> None:
    from gr_api.schemas.diagnosis_response import SnapshotMeta

    client, result = api_client
    progress = {k: result[k] for k in SnapshotMeta.model_fields}
    progress.update(
        run_status="running",
        plans=[
            {
                "plan_id": "mine",
                "label": "我的方案",
                "run_status": "running",
                "sections": {key: "pending" for key in view.SECTION_IDS},
                "error": None,
            }
        ],
    )

    async def pending(*args, **kwargs):
        return progress

    monkeypatch.setattr(svc, "get_result", pending)
    monkeypatch.setattr(svc, "get_report", pending)
    base = f"/v1/diagnosis/snapshots/{result['snapshot_id']}"
    for endpoint in ("result", "report", "data-quality"):
        response = client.get(f"{base}/{endpoint}")
        assert response.status_code == 202
        assert response.headers["retry-after"] == "1"
        assert response.json()["data"] == progress


def test_coverage_uses_version_thresholds_and_full_input_denominator() -> None:
    metric = {"industry_distribution": svc._ok({"Banks": 1.0})}
    assert (
        view.apply_coverage(metric, 1.0, {}, {"industry": 0.5})["industry_distribution"]["status"]
        == "unavailable"
    )
    assert (
        view.apply_coverage(metric, 0.9, {}, {"industry": 0.85})["industry_distribution"]["status"]
        == "unavailable"
    )
    params = {"coverage_thresholds": {"_default": {"unavailable": 0.4, "degraded": 0.7}}}
    assert view.apply_coverage(metric, 0.5, params)["industry_distribution"]["status"] == "degraded"
    assert view.apply_coverage(metric, 0.97, {})["industry_distribution"]["status"] == "ok"


def test_full_weight_distribution_is_a_valid_ratio_after_summing_many_holdings() -> None:
    from gr_api.schemas.diagnosis_response import ExposureMetrics

    holdings = [{"instrument_id": i, "weight": 0.02} for i in range(50)]
    result = svc._build_exposure_section(
        holdings,
        params={"topn": 50},
        industry=dict.fromkeys(range(50), "Banks"),
        category={},
        valuation={},
        has_fund=False,
        input_weight=Decimal(1),
        resolved_weight=Decimal(1),
    )
    ExposureMetrics.model_validate({k: v for k, v in result.items() if isinstance(v, dict)})
    assert result["industry_distribution"]["value"] == {"Banks": 1.0}
    assert result["topn"]["value"] == 1.0
