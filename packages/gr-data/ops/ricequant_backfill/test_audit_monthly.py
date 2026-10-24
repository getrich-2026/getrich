"""仓库外月度验收的纯 mock 回归，不访问业务库或供应商。"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest


spec = importlib.util.spec_from_file_location(
    "audit_monthly", Path(__file__).with_name("audit_monthly.py")
)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def manifest_fixture(*, gaps=2, day="2024-02-01"):
    coverage = []
    for iid in range(1, 5):
        missing = iid > 4 - gaps
        coverage.append(
            {
                "instrument_id": iid,
                "canonical_symbol": f"60000{iid}.SH",
                "request_code": f"60000{iid}.XSHG",
                "input_codes": [f"60000{iid}.XSHG"],
                "status": "partial_bundle" if missing else "included",
                "pieces": {"exposure": True, "specific_risk": True, "specific_return": not missing},
                "evidence": {"canonical": {"list_date": day}, "supplier": [{"listed_date": day}]},
            }
        )
    identity = {"contract": "rq_risk_model_v2", "purpose": "production", "model": "v1"}
    return {
        "day": day,
        "observed_at": "2026-10-23T01:00:00+00:00",
        "observation_id": "1" * 32,
        "identity": identity,
        "variant_id": audit.semantic_hash(identity),
        "purpose": "production",
        "coverage": coverage,
        "coverage_counts": {"candidate": 4, "complete": 4 - gaps},
        "universe": {"unresolved": []},
    }


@pytest.fixture
def evidence_case(monkeypatch):
    manifest = manifest_fixture()
    options = SimpleNamespace(
        purpose="production",
        universe_policy="listed_cn_a_v2",
        identity=manifest["identity"],
        variant_id=manifest["variant_id"],
    )
    version = "a" * 40
    digest = audit.semantic_hash(manifest)
    run_id = uuid.uuid4()
    receipt_id = uuid.uuid5(uuid.NAMESPACE_URL, f"factor.risk_bundle:{digest}:{version}")
    observed = datetime.fromisoformat(manifest["observed_at"])
    committed = observed + timedelta(seconds=10)
    quality = {
        "warnings": [],
        "covariance": {"warnings": []},
        "publication_eligible": False,
        "publication_reasons": ["complete_coverage_below_99_9_percent"],
    }
    receipt = {
        "receipt_id": receipt_id,
        "target": "factor.risk_bundle",
        "variant_id": options.variant_id,
        "manifest_hash": digest,
        "importer_version": version,
        "observation_id": manifest["observation_id"],
        "trading_day": date.fromisoformat(manifest["day"]),
        "rows_written": 12,
        "committed_at": committed,
        "quality": quality,
    }
    checkpoint = {
        "variant_id": options.variant_id,
        "observation_id": manifest["observation_id"],
        "trading_day": receipt["trading_day"],
        "capture_manifest_hash": digest,
        "captured_at": observed,
        "state": {
            "manifest_hash": digest,
            "purpose": "production",
            "contract": options.identity["contract"],
        },
        "import_receipt_id": receipt_id,
        "imported_at": committed,
        "watermark_date": receipt["trading_day"],
        "watermark_ts": None,
    }
    successes = [
        {
            "warning_count": 1,
            "started_at": observed,
            "finished_at": committed + timedelta(seconds=1),
            "request": {"receipt_id": str(receipt_id), "quality": quality, "replay": False},
        },
        {
            "warning_count": 1,
            "started_at": observed + timedelta(days=1),
            "finished_at": observed + timedelta(days=1, seconds=1),
            "request": {"receipt_id": str(receipt_id), "quality": quality, "replay": True},
        },
    ]

    def query(conn, sql, args=()):
        if "FROM ops.dataset_variant" in sql:
            return [
                {
                    "provider": "ricequant",
                    "dataset_name": "rq_risk_model",
                    "purpose": "production",
                    "identity": options.identity,
                }
            ]
        if sql.startswith("SELECT * FROM factor.model_run_binding"):
            return [
                {
                    "receipt_id": receipt_id,
                    "variant_id": options.variant_id,
                    "observation_id": manifest["observation_id"],
                    "trading_day": receipt["trading_day"],
                }
            ]
        if sql.startswith("SELECT * FROM ops.import_receipt"):
            return [receipt]
        if sql.startswith("SELECT receipt_id FROM ops.import_receipt"):
            return [{"receipt_id": receipt_id}]
        if sql.startswith("SELECT run_id FROM factor.model_run_binding"):
            return [{"run_id": run_id}]
        if "FROM ops.import_checkpoint" in sql:
            return [checkpoint]
        raise AssertionError(sql)

    monkeypatch.setattr(audit, "query", query)
    return SimpleNamespace(
        manifest=manifest,
        options=options,
        receipt=receipt,
        checkpoint=checkpoint,
        successes=successes,
        version=version,
        run_id=run_id,
        quality=quality,
    )


def test_low_coverage_known_ipo_passes_audit_but_stays_ineligible(evidence_case):
    case = evidence_case
    result = audit.audit_import_evidence(
        None,
        case.options,
        case.manifest,
        case.run_id,
        12,
        case.successes,
        importer_version=case.version,
    )
    assert result["status"] == "passed"
    assert result["publication_gate"]["eligible"] is False
    assert result["publication_gate"]["complete_fraction"] == 0.5
    assert result["publication_gate"]["known_ipo_continuation_allowed"] is True
    accepted = audit.coverage_acceptance(case.manifest)
    assert accepted["next_day_pending_instrument_ids"] == [3, 4]
    assert accepted["expected_coverage_warning_categories"] == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "other_day",
        "empty_supplier",
        "mixed_supplier_dates",
        "risk_missing",
        "provider_missing",
        "boundary",
    ],
)
def test_non_ipo_gap_rejected(mutation):
    manifest = manifest_fixture()
    row = manifest["coverage"][-1]
    if mutation == "other_day":
        row["evidence"]["canonical"]["list_date"] = "2024-01-31"
    elif mutation == "empty_supplier":
        row["evidence"]["supplier"] = []
    elif mutation == "mixed_supplier_dates":
        row["evidence"]["supplier"].append({"listed_date": "2024-01-31"})
    elif mutation == "risk_missing":
        row["pieces"]["specific_risk"] = False
    elif mutation == "provider_missing":
        row["status"] = "provider_not_returned"
    else:
        row["status"] = "universe_boundary_unknown"
    with pytest.raises(audit.AuditError, match="not_known_ipo"):
        audit.coverage_acceptance(manifest)


def test_complete_coverage_has_no_pending_stocks():
    result = audit.coverage_acceptance(manifest_fixture(gaps=0))
    assert result["publication_eligible"] is True
    assert result["next_day_pending_instrument_ids"] == []


@pytest.mark.parametrize(
    "mutation", ["warning_count", "numeric_warning", "eligibility", "checkpoint", "version"]
)
def test_existing_receipt_and_quality_checks_remain_strict(evidence_case, mutation):
    case = evidence_case
    if mutation == "warning_count":
        case.successes[-1]["warning_count"] = 2  # 两只IPO仍只有一个覆盖警告类别。
    elif mutation == "numeric_warning":
        case.quality["warnings"] = ["unexpected numerical warning"]
    elif mutation == "eligibility":
        case.quality["publication_eligible"] = True
    elif mutation == "checkpoint":
        case.checkpoint["import_receipt_id"] = uuid.uuid4()
    else:
        case.receipt["importer_version"] = "b" * 40
    with pytest.raises(audit.AuditError):
        audit.audit_import_evidence(
            None,
            case.options,
            case.manifest,
            case.run_id,
            12,
            case.successes,
            importer_version=case.version,
        )


@pytest.mark.parametrize(
    ("day", "request_code"), [("2025-02-14", "300114.XSHE"), ("2025-02-17", "302132.XSHE")]
)
def test_symbol_change_special_dates(day, request_code):
    manifest = manifest_fixture(gaps=0, day=day)
    row = manifest["coverage"][0]
    row.update(
        canonical_symbol="302132.SZ",
        input_codes=["300114.XSHE", "302132.XSHE"],
        request_code=request_code,
    )
    result = audit.audit_special_dates(None, manifest)
    assert result["symbol_change_300114_302132"]["request_code"] == request_code
    row["request_code"] = "000001.XSHE"
    with pytest.raises(audit.AuditError, match="request_or_coverage"):
        audit.audit_special_dates(None, manifest)


def test_000016_listing_and_full_day_event_are_read_from_real_schema(monkeypatch):
    manifest = manifest_fixture(gaps=0, day="2026-10-21")
    manifest["coverage"][0].update(canonical_symbol="000016.SZ", request_code="000016.XSHE")
    seen = []
    events = [{"suspend_type": "S", "suspend_timing": None}]

    def query(conn, sql, args=()):
        seen.append(sql)
        if "meta.instruments" in sql:
            return [
                {
                    "instrument_id": 1,
                    "symbol": "000016.SZ",
                    "list_date": date(1992, 3, 27),
                    "delist_date": None,
                }
            ]
        assert "market.stock_suspend_event" in sql
        assert args == (1, date(2026, 10, 21))
        return events

    monkeypatch.setattr(audit, "query", query)
    result = audit.audit_special_dates(None, manifest)
    assert result["000016_in_market_full_day_suspension"]["in_market"] is True
    assert len(seen) == 2
    events.append({"suspend_type": "R", "suspend_timing": None})
    with pytest.raises(audit.AuditError, match="full_day_suspension_not_verified"):
        audit.audit_special_dates(None, manifest)
