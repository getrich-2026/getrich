"""V1证券清单准入、完整分母与缓存隔离回归，不连接工作库。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from gr_api.errors import ApiError, Forbidden
from gr_api.schemas.diagnosis import SnapshotRequest
from gr_api.services import diagnosis as svc, diagnosis_publication as pub, diagnosis_scope as scope
from gr_data.diagnostic_publication import portfolio_hash
from pydantic import ValidationError


DAY = date(2026, 11, 5)
NOW = datetime(2026, 11, 10, tzinfo=timezone.utc)
METRICS = sorted(scope.METRICS)


def summary(weights: dict[int | str, str]) -> dict[str, Any]:
    return {
        "weight_mode": "user",
        "holdings": [
            {
                "instrument_id": i if isinstance(i, int) else None,
                "normalized_symbol": f"60000{i}.SH" if isinstance(i, int) else i,
                "input_weight": w,
            }
            for i, w in weights.items()
        ],
    }


def version(kind="security_universe") -> dict[str, Any]:
    declared = {
        "scope_type": kind,
        "as_of": str(DAY),
        "model": "v2",
        "run_id": "run",
        "metrics": METRICS,
        "calibrated": False,
        "security_ids": [1, 2, 3],
        "security_hash": "security",
        "universe_admission_id": "admission",
    }
    if kind == "exact_portfolio":
        declared.update(
            holdings={"1": ".4", "2": ".6"},
            portfolio_hash=portfolio_hash({1: Decimal(".4"), 2: Decimal(".6")}),
        )
    return {
        "data_version_id": "version",
        "as_of_date": DAY,
        "published_at": NOW,
        "contract_version": "diag-publication-v2-universe"
        if kind == "security_universe"
        else "diag-publication-v1",
        "available_options": {"publication_scope": declared},
    }


class RiskDb:
    def __init__(self, *, missing_specific: int | None = None):
        self.query = ""
        self.missing_specific = missing_specific

    @asynccontextmanager
    async def cursor(self, **kwargs):
        assert kwargs.get("binary") is True
        yield self

    async def execute(self, query, params=None):
        self.query = query
        self.params = params

    async def fetchall(self):
        if "SELECT instrument_id,symbol" in self.query:
            return [{"instrument_id": i, "symbol": f"60000{i}.SH"} for i in (1, 2, 3, 4)]
        if "SELECT m.*" in self.query:
            return [
                {
                    "run_id": "run",
                    "model_id": "model",
                    "model_version": "observation",
                    "metrics": METRICS,
                    "units_evidence": {"F": "annual"},
                    "evidence": {},
                    "receipt_id": "receipt",
                    "horizon": "daily",
                    "trading_day": DAY,
                    "observed_at": NOW,
                    "source": "ricequant",
                    "annualization_basis": "annual_252",
                    "units": {
                        "model": "v2",
                        "covariance": "pct2_annual",
                        "specific_risk": "pct2_annual",
                    },
                    "factor_order": ["f"],
                    "calibrated": False,
                }
            ]
        return [
            {
                "instrument_id": i,
                "exposure": [float(i)],
                "specific_var": None if i == self.missing_specific else float(i * 100),
                "status": "included",
                "exposure_at": NOW,
                "specific_at": NOW,
            }
            for i in (1, 2, 3, 4)
        ]

    async def fetchone(self):
        return {"cov_flat": [400.0]}


@pytest.mark.anyio
async def test_universe_allows_different_weights_in_one_publication():
    db: Any = RiskDb()
    data = version()
    token = pub.current.set(pub.PublishedDiagnosticContext("version", DAY, NOW, data))
    try:
        results = []
        for weights in ({1: Decimal(".4"), 2: Decimal(".6")}, {1: Decimal(".7"), 2: Decimal(".3")}):
            details, original = scope.initial_coverage(
                summary({i: str(w) for i, w in weights.items()})
            )
            loaded = await svc._load_risk_model(
                db,
                list(weights),
                spec={
                    "params": {
                        "cov_methods": ["forward"],
                        "forward_model_selector": {
                            "source": "ricequant",
                            "model": "v2",
                            "industry_mapping": "sws_2021",
                        },
                    }
                },
                as_of=DAY,
                weights=weights,
                assessment=details,
                input_weights=original,
            )
            assert loaded is not None
            assert details["status"] == "complete" and details["covered_count"] == 2
            result = svc._scoped_risk([svc.CalcHolding(i, w) for i, w in weights.items()], loaded)
            results.append(result.facts["annual_variance"])
        assert results[0] == pytest.approx(1.6**2 * 0.04 + 0.4**2 * 0.01 + 0.6**2 * 0.02)
        assert results[1] == pytest.approx(1.3**2 * 0.04 + 0.7**2 * 0.01 + 0.3**2 * 0.02)
    finally:
        pub.current.reset(token)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("weights", "missing_specific", "reason"),
    [
        ({1: ".5", 4: ".5"}, None, "outside_security_universe"),
        ({1: ".5", 2: ".5"}, 2, "specific_risk_missing"),
        ({1: ".8", "UNKNOWN": ".2"}, None, "unresolved_symbol"),
    ],
)
async def test_incomplete_holdings_never_compute_renormalized_subset(
    weights, missing_specific, reason
):
    db: Any = RiskDb(missing_specific=missing_specific)
    token = pub.current.set(pub.PublishedDiagnosticContext("version", DAY, NOW, version()))
    try:
        details, original = scope.initial_coverage(summary(weights))
        quantized = {i: w / sum(original.values()) for i, w in original.items()}
        loaded = await svc._load_risk_model(
            db,
            list(original),
            spec={
                "params": {
                    "cov_methods": ["forward"],
                    "forward_model_selector": {
                        "source": "ricequant",
                        "model": "v2",
                        "industry_mapping": "sws_2021",
                    },
                }
            },
            as_of=DAY,
            weights=quantized,
            assessment=details,
            input_weights=original,
        )
        assert loaded is None
        assert details["status"] == "incomplete"
        assert reason in {x["reason"] for x in details["missing"]}
        assert details["covered_count"] == 1
        assert Decimal(details["covered_weight"]) < 1
        issue = next(x for x in details["missing"] if x["reason"] == reason)
        assert issue["symbol"] and Decimal(issue["weight"]) > 0
    finally:
        pub.current.reset(token)


def test_exact_scope_rejects_reweighting_and_date_or_metric_expansion():
    data = version("exact_portfolio")
    valid = SimpleNamespace(plan_index=0, summary=summary({1: ".4", 2: ".6"}))
    scope.validate_request(data, [valid], DAY, METRICS)
    for plans, day, metrics in [
        ([SimpleNamespace(plan_index=0, summary=summary({1: ".5", 2: ".5"}))], DAY, METRICS),
        ([valid], date(2026, 11, 6), METRICS),
        ([valid], DAY, ["l4_effective_count"]),
    ]:
        with pytest.raises(ApiError) as exc:
            scope.validate_request(data, plans, day, metrics)
        assert exc.value.http_status == 422


def test_scope_identity_and_contract_fail_closed():
    data = version()
    data["contract_version"] = "diag-publication-v1"
    with pytest.raises(ApiError) as exc:
        scope.scope(data)
    assert exc.value.http_status == 503


def test_full_scope_prevents_ready_or_missing_cache_pollution():
    base = {
        "weight_mode": "user",
        "quantized": {1: 100_000_000},
        "resolved_as_of_date": DAY,
        "spec_version": "spec",
        "data_fingerprint": "version",
        "resolved_options": {},
    }
    cases = [
        summary({1: "1"}),
        summary({1: ".8", "UNKNOWN_A": ".2"}),
        summary({1: ".8", "UNKNOWN_B": ".2"}),
        summary({1: ".7", "UNKNOWN_A": ".3"}),
    ]
    keys = [
        svc._calculation_hash(**base, full_input_scope_hash=scope.cache_scope(x)) for x in cases
    ]
    assert len(set(keys)) == 4
    cache: dict[str, Any] = {keys[0]: {"annual_variance": {"status": "degraded", "value": 0.05}}}
    assert all(k not in cache for k in keys[1:])
    cache[keys[1]] = {"missing": [{"symbol": "UNKNOWN_A", "weight": ".2"}]}
    assert keys[2] not in cache and keys[3] not in cache
    assert scope.cache_scope(summary({1: ".8", "UNKNOWN_A": ".2"})) == scope.cache_scope(
        summary({"UNKNOWN_A": "20", 1: "80"})
    )


@pytest.mark.parametrize(
    "metrics",
    [
        ["beta"],
        ["l4_effective_count"],
        ["annual_variance", "volatility", "daily_prediction_volatility", "beta"],
    ],
)
def test_request_rejects_unadmitted_metrics(metrics):
    with pytest.raises(ValidationError):
        SnapshotRequest.model_validate(
            {
                "plans": [{"plan_id": "p", "holdings": [{"symbol": "600001.SH", "weight": "1"}]}],
                "metrics": metrics,
            }
        )


@pytest.mark.anyio
@pytest.mark.parametrize("reader", [svc.get_result, svc.get_report])
async def test_user_cannot_read_other_users_snapshot(monkeypatch, reader):
    owner, other, snapshot_id = uuid4(), uuid4(), uuid4()

    class OwnerDb:
        @asynccontextmanager
        async def cursor(self):
            yield self

        async def execute(self, *args):
            pass

        async def fetchone(self):
            return {"user_id": owner}

    db: Any = OwnerDb()
    with pytest.raises(Forbidden):
        await reader(db, snapshot_id, user_id=str(other))


@pytest.mark.anyio
async def test_user_cannot_recompute_other_users_snapshot(monkeypatch):
    from gr_api.schemas.diagnosis import RecomputeRequest

    owner, other, snapshot_id = uuid4(), uuid4(), uuid4()

    class OwnerDb:
        @asynccontextmanager
        async def cursor(self):
            yield self

        async def execute(self, *args):
            pass

        async def fetchone(self):
            return {"user_id": owner}

    async def request(db, *, create, **kwargs):
        return await create("hash")

    monkeypatch.setattr(svc, "_with_idempotency", request)
    db: Any = OwnerDb()
    with pytest.raises(Forbidden):
        await svc.recompute_snapshot(db, snapshot_id, RecomputeRequest(), user_id=str(other))


def test_base_business_data_is_filtered_without_changing_input_identity_or_denominator():
    token = pub.current.set(pub.PublishedDiagnosticContext("version", DAY, NOW, version()))
    try:
        assert scope.base_ids([1, 2, 4]) == [1, 2]
        weights, missing = scope.input_weights(summary({1: ".4", 4: ".6"}))
        assert weights == {1: Decimal(".4"), 4: Decimal(".6")}
        assert not missing
    finally:
        pub.current.reset(token)


@pytest.mark.anyio
@pytest.mark.parametrize("case", ["complete", "unknown", "nonmember", "missing_data"])
async def test_computed_payload_survives_actual_serialized_result_and_report_assembly(
    monkeypatch, case
):
    """完整取数/计算结果过落库JSON再走presentation，覆盖旧scalar与新结构兼容。"""
    import json

    from gr_api.diagnosis_calc.weights import InputRow, normalize_plan
    from gr_api.services import diagnosis_presentation as presentation

    data = version()
    token = pub.current.set(pub.PublishedDiagnosticContext("version", DAY, NOW, data))
    db: Any = RiskDb(missing_specific=1 if case == "missing_data" else None)

    async def category(*args, **kwargs):
        return {1: {"market": "cn_a", "asset_category": "equity"}}

    async def valuation(*args, **kwargs):
        return {1: svc.Valuation(DAY, Decimal("2e11"), Decimal(".5"))}

    async def previous(*args, **kwargs):
        return date(2025, 10, 27)

    async def observations(db, ids, **kwargs):
        return {i: [] for i in ids}, {i: {} for i in ids}

    monkeypatch.setattr(svc, "_fetch_category", category)
    monkeypatch.setattr(svc, "_fetch_valuation", valuation)
    monkeypatch.setattr(svc, "_trading_day_before", previous)
    monkeypatch.setattr(svc, "_fetch_daily_observations", observations)
    iid = 4 if case == "nonmember" else 1
    rows = [
        InputRow(
            0,
            f"60000{iid}.SH",
            Decimal(".8") if case == "unknown" else Decimal(1),
            f"60000{iid}.SH",
            {"instrument_id": iid, "symbol": f"60000{iid}.SH", "name": "证券"},
        )
    ]
    if case == "unknown":
        rows.append(InputRow(1, "UNKNOWN", Decimal(".2"), "UNKNOWN", None))
    normalized = normalize_plan(rows)
    row = {
        "plan_index": 0,
        "plan_id": "mine",
        "label": "我的组合",
        "weight_mode": normalized.weight_mode,
        "input_context": normalized.summary,
        "status": "succeeded",
    }
    item = svc.PlanInput(
        0, "mine", "我的组合", [], row["weight_mode"], row["input_context"], normalized.quantized
    )
    spec = {
        "params": {
            "cov_methods": ["forward", "historical"],
            "mktcap_bands_yi": [100, 500, 1000, 3000],
            "pb_bands": [1, 2, 4, 8],
        }
    }
    spec["params"]["forward_model_selector"] = {
        "source": "ricequant",
        "model": "v2",
        "industry_mapping": "sws_2021",
    }
    options = {
        "industry_scheme": None,
        "industry_scheme_version": None,
        "benchmark_instrument_id": None,
        "benchmark_version": None,
        "correlation_window": {"start": "2025-10-28", "end": str(DAY)},
        "beta_window": {"start": "2025-10-28", "end": str(DAY)},
        "replay_start": None,
        "stats_window": None,
    }
    try:
        payload, facts = await svc._compute_plan(
            db, item=item, spec=spec, as_of=DAY, options=options
        )
        assert isinstance(facts["model"]["coverage"], float)
        assert facts["model"]["model_coverage"]["status"] == (
            "complete" if case == "complete" else "incomplete"
        )
        expected_coverage = 1.0 if case == "complete" else (0.8 if case == "unknown" else 0.0)
        assert facts["model"]["coverage"] == expected_coverage
        row["payload"] = json.loads(json.dumps(payload))
        row["data_quality"] = json.loads(json.dumps(facts))
        snapshot = {
            "snapshot_id": uuid4(),
            "resolved_spec_version": "spec",
            "resolved_as_of_date": DAY,
            "resolved_intent": "single_portfolio",
            "data_fingerprint": "version",
            "data_snapshot_at": NOW,
            "resolved_options": options,
            "base_snapshot_id": None,
        }
        result = presentation.assemble(
            snapshot, spec, [row], "succeeded", report_mode=svc._report_mode
        )
        risk = result["plans"][0]["section_b"]["value"]
        assert (
            result["data_quality"]["plans"][0]["coverage_summary"]["risk_model"]
            == expected_coverage
        )
        if case == "complete":
            assert risk["annual_variance"]["value"] == pytest.approx(0.05)
            assert risk["model_coverage"]["covered_count"] == 1
            assert risk["volatility"]["by_method"]["forward"]["value"] == pytest.approx(0.05**0.5)
        else:
            assert risk["annual_variance"]["status"] == "unavailable"
            assert risk["daily_prediction_volatility"]["status"] == "unavailable"
            assert risk["model_coverage"]["missing"]
        report = presentation.report(result, "retail", industry_labels={})
        assert (
            report["data_quality"]["plans"][0]["coverage_summary"]["risk_model"]
            == expected_coverage
        )
        assert report["snapshot_id"] == result["snapshot_id"]
        assert report["sections"]
    finally:
        pub.current.reset(token)


@pytest.mark.anyio
async def test_real_universe_reader_binds_json_security_ids_as_bigint_array():
    """真实隔离PG覆盖JSON整数清单与BIGINT[]等号；mock不能发现42883。"""
    import os
    from dataclasses import replace

    import psycopg
    from gr_data.config import load_postgres, make_pg_dsn
    from gr_data.db import DictConnection
    from gr_tools.config import load_environment
    from psycopg.rows import dict_row

    database = os.environ.get("GETRICH_DIAG_V1_ISOLATED_DB")
    if not database:
        pytest.skip("requires explicit isolated V1 database with an available universe publication")
    if not database.startswith("getrich_diag_"):
        pytest.fail("test refuses non-isolated PostgreSQL database", pytrace=False)
    cfg = replace(load_postgres(load_environment()), database=database)
    try:
        conn = await DictConnection.connect(make_pg_dsn(cfg), autocommit=True, row_factory=dict_row)
    except psycopg.OperationalError:
        pytest.fail("isolated PostgreSQL connection unavailable", pytrace=False)
    async with conn:
        await conn.execute("SET default_transaction_read_only=on")
        async with pub.consistent_read(conn):
            data = await pub.require_publication(conn)
            declared = scope.scope(data)
            assert declared["scope_type"] == "security_universe"
            ids = declared["security_ids"][:2]
            assert len(ids) == 2
            weights = {ids[0]: Decimal(".3"), ids[1]: Decimal(".7")}
            assessment, original = scope.initial_coverage(
                summary({i: str(w) for i, w in weights.items()})
            )
            loaded = await svc._load_risk_model(
                conn,
                ids,
                spec={
                    "params": {
                        "cov_methods": ["forward"],
                        "forward_model_selector": {
                            "source": "ricequant",
                            "model": "v2",
                            "industry_mapping": "sws_2021",
                        },
                    }
                },
                as_of=data["as_of_date"],
                weights=weights,
                assessment=assessment,
                input_weights=original,
            )
            assert loaded is not None
            assert assessment["status"] == "complete"
            assert assessment["covered_count"] == 2
            assert assessment["missing"] == []
            # 真实unknown20%路径：完整读取/计算与即将写库的JSON编码都必须通过。
            import json

            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT symbol FROM meta.instruments WHERE instrument_id=%s", (ids[0],)
                )
                known = await cur.fetchone()
            assert known is not None
            req = SnapshotRequest.model_validate(
                {
                    "plans": [
                        {
                            "plan_id": "unknown",
                            "holdings": [
                                {"symbol": known["symbol"], "weight": ".8"},
                                {"symbol": "888888.SH", "weight": ".2"},
                            ],
                        }
                    ]
                }
            )
            spec = await svc.get_active_spec_version(conn)
            plans = await svc._normalize_request_plans(conn, req.plans, as_of=data["as_of_date"])
            options = await svc._resolve_options(
                conn,
                requested=req.options,
                params=spec["params"],
                available=data["available_options"],
                as_of=data["as_of_date"],
            )
            payload, facts = await svc._compute_plan(
                conn, item=plans[0], spec=spec, as_of=data["as_of_date"], options=options
            )
            json.dumps(payload)
            json.dumps(facts)
            assert payload["section_b"]["value"]["annual_variance"]["status"] == "unavailable"
            assert facts["model"]["coverage"] == 0.8
            assert facts["model"]["coverage_basis"] == "full_input"
            assert facts["model"]["model_date"] == str(data["as_of_date"])
            assert facts["model"]["model_coverage"]["missing"][0]["symbol"] == "888888.SH"


def test_full_input_numeric_coverage_is_not_discounted_twice():
    from gr_api.diagnosis_calc.coverage import FULL_PORTFOLIO_MODEL_METRICS, apply_model_coverage
    from gr_api.diagnosis_calc.metrics import ok, unavailable

    na = unavailable(reason_code="data_not_validated", reason="not admitted")
    sections: dict[str, Any] = {
        "section_b": {"volatility": {"primary": None, "by_method": {"forward": na}}},
        "section_d": {},
    }
    for section, name in FULL_PORTFOLIO_MODEL_METRICS:
        sections[section][name] = na
    for name in ("avg_pairwise_correlation", "high_correlation_pairs"):
        sections["section_d"][name] = {
            "primary": "forward",
            "by_method": {"forward": ok(0.5, method="forward")},
        }
    _, result = apply_model_coverage(
        sections["section_b"],
        sections["section_d"],
        resolved_weight=0.8,
        model_facts={"coverage": 0.8, "coverage_basis": "full_input"},
        params={},
    )
    metric = result["avg_pairwise_correlation"]["by_method"]["forward"]
    assert metric["status"] == "degraded"
    assert "80.0%" in metric["reason"]
    _, legacy = apply_model_coverage(
        sections["section_b"],
        sections["section_d"],
        resolved_weight=0.8,
        model_facts={"coverage": 0.8},
        params={},
    )
    assert legacy["avg_pairwise_correlation"]["by_method"]["forward"]["status"] == "unavailable"
