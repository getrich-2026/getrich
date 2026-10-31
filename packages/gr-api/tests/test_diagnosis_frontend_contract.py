"""前端契约回归：区块状态、请求隔离、有限数、报告及 HTTP/SSE 一致性。"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gr_api.deps import get_current_user, get_db
from gr_api.diagnosis_calc.exposure import (
    CalcHolding,
    IndustryAssignment,
    Valuation,
    compute_exposure,
)
from gr_api.diagnosis_calc.weights import WEIGHT_UNITS, InputRow, normalize_plan
from gr_api.routers.diagnosis import _stream_sections, router
from gr_api.schemas.diagnosis import RecomputeRequest, SnapshotRequest
from gr_api.schemas.diagnosis_response import (
    CalculationPayload,
    CorrelationMatrix,
    CovarianceSpec,
    DiagnosisResult,
    ExposureMetrics,
    InstrumentFacts,
    MetricValue,
    ReplaySeries,
    ReportResponse,
    SectionResult,
)
from gr_api.services import diagnosis as svc, diagnosis_presentation as view
from pydantic import FiniteFloat, ValidationError


AS_OF = date(2026, 10, 29)
SPEC = {
    "params": {
        "cov_methods": ["forward", "historical"],
        "mktcap_bands_yi": [100, 500, 1000, 3000],
        "pb_bands": [1, 2, 4, 8],
    }
}
OPTIONS = {
    "industry_scheme": "sw2021",
    "industry_scheme_version": "2021",
    "benchmark_instrument_id": None,
    "benchmark_version": None,
    "correlation_window": {"start": "2025-10-28", "end": "2026-10-29"},
    "beta_window": {"start": "2025-10-28", "end": "2026-10-29"},
    "replay_start": None,
    "stats_window": None,
}


def fixture_row(*, coverage: float = 1.0, failed: bool = False) -> dict[str, Any]:
    """浦发银行加一行可选的未识别代码，按真实规范化与计算函数构造共享载体。"""
    rows = [
        InputRow(
            0,
            "600000.SH",
            Decimal(str(coverage)),
            "600000.SH",
            {"instrument_id": 1, "symbol": "600000.SH", "name": "浦发银行"},
        )
    ]
    if coverage < 1:
        rows.append(InputRow(1, "UNKNOWN", Decimal(str(1 - coverage)), "UNKNOWN", None))
    plan = normalize_plan(rows)
    metrics, facts = compute_exposure(
        [CalcHolding(i, Decimal(u) / WEIGHT_UNITS) for i, u in plan.quantized.items()],
        as_of=AS_OF,
        params=SPEC["params"],
        industry_scheme="sw2021",
        industry={1: IndustryAssignment("801780", "银行")},
        category={1: {"market": "cn_a", "asset_category": "equity"}},
        valuation={1: Valuation(AS_OF, Decimal("2e11"), Decimal("0.5"))},
    )
    payload = CalculationPayload.model_validate(
        {
            "cov": {"requested": ["forward", "historical"], "primary": None, "computed": []},
            "section_a": {"status": "ready", "value": metrics},
            **{key: svc._unavailable_section(key) for key in svc.SECTION_REASONS},
        }
    ).model_dump(mode="json")
    return {
        "plan_index": 0,
        "plan_id": "mine",
        "label": "我的方案",
        "weight_mode": plan.weight_mode,
        "input_context": plan.summary,
        "status": "failed" if failed else "partially_succeeded",
        "payload": None if failed else payload,
        "data_quality": None if failed else facts,
    }


def fixture_snapshot() -> dict[str, Any]:
    return {
        "snapshot_id": uuid4(),
        "resolved_spec_version": "v1-model-20261031",
        "resolved_as_of_date": AS_OF,
        "resolved_intent": "single_portfolio",
        "data_fingerprint": "fixture",
        "data_snapshot_at": datetime(2026, 10, 29, 18, tzinfo=ZoneInfo("Asia/Shanghai")),
        "resolved_options": OPTIONS,
        "base_snapshot_id": None,
    }


def fixture_result(*, coverage: float = 1.0, failed: bool = False) -> tuple[dict, dict]:
    row = fixture_row(coverage=coverage, failed=failed)
    shared = deepcopy(row)
    result = view.assemble(
        fixture_snapshot(), SPEC, [row], row["status"], report_mode=svc._report_mode
    )
    return result, shared


def test_all_sections_have_explicit_states_and_input_echo() -> None:
    result, _ = fixture_result()
    DiagnosisResult.model_validate(result)
    plan = result["plans"][0]
    a = plan["section_a"]["value"]
    assert a["hhi"]["value"] == 1
    assert [t["n"] for t in a["topn"]["value"]] == [1, 3, 5]
    assert a["max_industry"]["value"]["industry_name"] == "银行"
    assert plan["input"]["holdings"][0]["name"] == "浦发银行"
    assert plan["input"]["calculation_holdings"][0]["calculation_weight"] == 1
    assert plan["section_b"]["reason_code"] == "feature_not_available"
    assert plan["section_c"]["reason_code"] == "feature_not_available"
    assert plan["profile"]["reason_code"] == "spec_not_defined"
    assert all(b["status"] == "unavailable" for b in plan["blindspots"]["value"])
    assert result["comparison"]["reason_code"] == "not_applicable"
    assert plan["cov"] == {
        "requested": ["forward", "historical"],
        "forward_model": None,
        "primary": None,
        "computed": [],
    }
    assert result["options"] == OPTIONS
    assert result["run_status"] == "partially_succeeded"
    assert all(plan[key] is not None for key in view.SECTION_IDS)


def test_missing_input_changes_metrics_without_mutating_cache() -> None:
    result, shared = fixture_result(coverage=0.5)
    plan = result["plans"][0]
    a = plan["section_a"]["value"]
    assert plan["input"]["resolved_weight"] == 0.5
    assert a["hhi"]["status"] == "unavailable"
    assert "value" not in a["hhi"]
    assert a["topn"]["status"] == "unavailable"
    # 带缺失档的分布只降级，不判不可用（PA-13）
    assert a["industry_distribution"]["status"] == "degraded"
    assert shared["payload"]["section_a"]["value"]["hhi"]["status"] == "ok"
    issues = result["data_quality"]["plans"][0]["issues"]
    assert any(i["paths"] == ["/holdings/1"] and i["code"] == "unresolved" for i in issues)
    assert result["data_quality"]["plans"][0]["coverage_summary"]["symbol_resolution"] == 0.5


def test_degraded_coverage_remains_visible_in_both_report_levels() -> None:
    result, _ = fixture_result(coverage=0.9)
    assert result["plans"][0]["section_a"]["value"]["hhi"]["status"] == "degraded"
    for level in ("retail", "pro"):
        report = view.report(result, level, industry_labels={"801780": "银行"})
        ReportResponse.model_validate(report)
        assert report["disclosures"] == result["disclosures"]
        assert report["data_quality"] == result["data_quality"]
        sections = {s["section_id"]: s for s in report["sections"]}
        assert sections["mine:risk"]["content"]["reason_code"] == "feature_not_available"
        assert sections["mine:instrument"]["content"]["value"][0]["input"][
            "unresolved_weight"
        ] == pytest.approx(0.1)
        blocks = sections["mine:exposure"]["content"]["value"]
        cards = blocks[0]["items"]
        top1 = next(c for c in cards if c["metric_id"] == "top1")
        assert top1["value"]["status"] == "degraded"
        assert top1["value"]["value"] == pytest.approx(0.9)
        assert ("hhi" in {c["metric_id"] for c in cards}) == (level == "pro")
        industry = next(b for b in blocks if b.get("metric_id") == "industry_distribution")
        assert industry["labels"] == {"801780": "银行"}
        cap = next(b for b in blocks if b.get("metric_id") == "mktcap_distribution")
        assert cap["labels"]["1000_3000"] == "1000–3000 亿元"
        assert cap["labels"]["missing_or_invalid"] == "缺失或异常"


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
        {
            "plans": [{"plan_id": "p", "holdings": [{"symbol": "A"}]}],
            "options": {"correlation_window": {"start": "2026-01-02", "end": "2026-01-02"}},
        },
        {"plans": [{"plan_id": "p", "holdings": [{"symbol": "A"}]}], "options": {"bogus": 1}},
    ],
)
def test_requests_reject_ambiguous_or_nonfinite_input(body: dict) -> None:
    with pytest.raises(ValidationError):
        SnapshotRequest.model_validate(body)


@pytest.mark.parametrize(
    "body",
    [
        {"reset_to_default": ["benchmark", "benchmark"]},
        {"options": {"benchmark": "000300.SH"}, "reset_to_default": ["benchmark"]},
        {"reset_to_default": ["unknown"]},
    ],
)
def test_recompute_request_rejects_conflicting_reset(body: dict) -> None:
    with pytest.raises(ValidationError):
        RecomputeRequest.model_validate(body)


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


def test_topn_must_contain_one_three_and_five_exactly_once() -> None:
    result, _ = fixture_result()
    metrics = deepcopy(result["plans"][0]["section_a"]["value"])
    metrics["topn"]["value"] = metrics["topn"]["value"][:2]
    with pytest.raises(ValidationError, match="n=1, 3 and 5"):
        ExposureMetrics.model_validate(metrics)


def test_roe_with_value_requires_report_year_and_announcement_date() -> None:
    facts = {
        "total_mv_yi": {
            "status": "unavailable",
            "reason_code": "data_not_validated",
            "reason": "x",
        },
        "pb": {"status": "unavailable", "reason_code": "data_not_validated", "reason": "x"},
        "valuation_date": None,
        "roe": {"status": "ok", "value": 0.12, "method": "exact"},
        "roe_report_year": None,
        "roe_ann_date": None,
    }
    with pytest.raises(ValidationError, match="roe_report_year"):
        InstrumentFacts.model_validate(facts)


def test_replay_nav_must_be_positive_and_truncation_consistent() -> None:
    base = {
        "build_start": "2026-01-05",
        "dates": ["2026-01-05", "2026-01-06"],
        "nav": [1.0, 0.0],
        "stock_position": [1.0, 1.0],
        "unexecuted": [],
        "limiting_instrument_ids": [],
    }
    with pytest.raises(ValidationError):
        ReplaySeries.model_validate(base)
    with pytest.raises(ValidationError, match="together"):
        ReplaySeries.model_validate({**base, "nav": [1.0, 1.1], "truncated_at": "2026-01-06"})


def test_forward_model_is_required_exactly_when_forward_was_computed() -> None:
    with pytest.raises(ValidationError, match="forward_model"):
        CovarianceSpec.model_validate(
            {"requested": ["forward"], "primary": "forward", "computed": ["forward"]}
        )
    # historical 已算出而 forward 未算出时，primary 保持 null，不以历史口径顶替
    CovarianceSpec.model_validate(
        {"requested": ["forward", "historical"], "primary": None, "computed": ["historical"]}
    )


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

    async def recompute(*args, **kwargs):
        raise svc.BaseDataVersionUnavailableError("the original data version cannot be reproduced")

    monkeypatch.setattr(svc, "get_result", get_result)
    monkeypatch.setattr(svc, "create_snapshot", create)
    monkeypatch.setattr(svc, "get_report", report)
    monkeypatch.setattr(svc, "recompute_snapshot", recompute)
    with TestClient(app) as client:
        yield client, result


SECURITY_HEADERS = (
    "content-security-policy",
    "x-frame-options",
    "x-content-type-options",
    "referrer-policy",
)


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
    for name in SECURITY_HEADERS:
        assert name in report.headers


def test_recompute_conflict_has_stable_code_and_security_headers(api_client) -> None:
    client, result = api_client
    response = client.post(
        f"/v1/diagnosis/snapshots/{result['snapshot_id']}/recompute",
        json={"options": {"correlation_window": {"start": "2026-01-05", "end": "2026-06-30"}}},
    )
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "BASE_DATA_VERSION_UNAVAILABLE"
    assert error["retryable"] is False
    for name in SECURITY_HEADERS:
        assert name in response.headers


def test_recompute_validates_body_and_idempotency_key(api_client) -> None:
    client, result = api_client
    url = f"/v1/diagnosis/snapshots/{result['snapshot_id']}/recompute"
    response = client.post(url, json={"reset_to_default": ["benchmark", "benchmark"]})
    assert response.status_code == 422
    response = client.post(url, headers={"Idempotency-Key": "invalid"}, json={})
    assert response.status_code == 422
    assert response.json()["error"]["issues"][0]["path"] == "/headers/Idempotency-Key"


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


def test_openapi_exposes_sections_options_and_success_statuses(api_client) -> None:
    client, _ = api_client
    schema = client.get("/openapi.json").json()
    submit = schema["paths"]["/v1/diagnosis/snapshots"]["post"]
    assert {"200", "201", "202", "422", "409"} <= submit["responses"].keys()
    assert any(p["name"] == "Idempotency-Key" for p in submit["parameters"])
    request = schema["components"]["schemas"]["SnapshotRequest"]["properties"]
    assert "user_level" not in request
    assert "options" in request
    assert "/v1/diagnosis/snapshots/{snapshot_id}/recompute" in schema["paths"]
    # Pydantic 可按输入/输出模式拆分组件名称，断言实际模型而非自动生成的键名。
    results = [
        model
        for model in schema["components"]["schemas"].values()
        if model.get("title") == "DiagnosisResult"
    ]
    assert results and all(
        {"comparison", "options", "base_snapshot_id"} <= model["properties"].keys()
        for model in results
    )


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
                "sections": dict.fromkeys(view.SECTION_IDS, "pending"),
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


def test_valuation_lag_is_listed_in_data_quality() -> None:
    row = fixture_row()
    row["data_quality"]["valuation_lagged"] = [1]
    row["data_quality"]["valuation_lagged_weight"] = 1.0
    result = view.assemble(
        fixture_snapshot(), SPEC, [row], row["status"], report_mode=svc._report_mode
    )
    issues = result["data_quality"]["plans"][0]["issues"]
    lag = next(i for i in issues if i["code"] == "valuation_lagged")
    assert "600000.SH" in lag["reason"]
    assert "100.0%" in lag["reason"]
