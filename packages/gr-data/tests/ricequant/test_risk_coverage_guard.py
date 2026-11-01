"""经验包络、未知归因、整数边界、月去重和前视隔离。"""

from __future__ import annotations

import copy
from collections import Counter

import pytest
from gr_data.common import ricequant_coverage_guard as guard


def envelope(model="v1"):
    return {
        "model": model,
        "max_missing_count": 3,
        "max_missing_fraction": {"numerator": 3, "denominator": 5164},
        "max_unknown_reason_count_observed": 0,
    }


def missing(
    day="2020-01-02",
    symbol="000001.SZ",
    listed="2020-01-02",
    pieces=None,
    status="partial_bundle",
    model="v1",
    run="r1",
):
    return {
        "model": model,
        "day": day,
        "target_symbol": symbol,
        "instrument_id": 77,
        "run_id": run,
        "status": status,
        "pieces": pieces or {"exposure": True, "specific_return": False, "specific_risk": True},
        "evidence": {"canonical": {"symbol": symbol, "list_date": listed, "instrument_id": 999}},
        "next_day": "2020-01-03",
        "next_day_status": "included",
        "next_day_pieces": dict.fromkeys(guard.INDIVIDUAL, True),
    }


def daily(day="2020-01-02", n=1696, absent=1, model="v1", run="r1"):
    return {
        "model": model,
        "day": day,
        "candidate": n,
        "complete": n - absent,
        "run_id": run,
    }


def interfaces(**changes):
    return {**dict.fromkeys(guard.INTERFACES, True), **changes}


@pytest.mark.parametrize(
    "candidate,expected",
    [
        (1, 1),
        (1000, 1),
        (1696, 1),
        (1721, 1),
        (1722, 2),
        (3442, 2),
        (3443, 3),
        (5164, 3),
        (100000, 3),
    ],
)
def test_integer_ceiling_with_max_count_and_no_arbitrary_multiplier(candidate, expected):
    assert guard.allowed_missing(candidate, envelope()) == expected


@pytest.mark.parametrize("candidate", [0, -1, True, 1.5])
def test_invalid_denominator_is_rejected(candidate):
    result = guard.evaluate_day(
        envelope(),
        {"model": "v1", "day": "2020-01-02", "candidate": candidate, "complete": 0},
        [],
        interfaces(),
    )
    assert not result["passes_coverage_guard"]
    assert "invalid_coverage_denominator" in result["reject_reasons"]


def test_single_ipo_in_smaller_market_is_allowed_but_excess_total_is_not():
    row = missing()
    result = guard.evaluate_day(envelope(), daily(), [row], interfaces())
    assert result["passes_coverage_guard"] and result["allowed_missing_count"] == 1
    second = missing(symbol="000002.SZ")
    result = guard.evaluate_day(envelope(), daily(absent=2), [row, second], interfaces())
    assert (
        not result["passes_coverage_guard"]
        and "missing_count_above_empirical_envelope" in result["reject_reasons"]
    )
    assert row["instrument_id"] != row["evidence"]["canonical"]["instrument_id"]


def test_ipo_requires_all_three_facts_and_ignores_next_day():
    row = missing()
    assert guard.classify_missing(row)["reason"] == "ipo_first_day_missing_specific_return"
    changed = copy.deepcopy(row)
    changed["next_day_status"] = "partial_bundle"
    changed["next_day_pieces"]["specific_return"] = False
    assert guard.classify_missing(changed)["reason"] == guard.classify_missing(row)["reason"]
    for modified in [
        missing(listed="2020-01-01"),
        missing(pieces={"exposure": True, "specific_return": False, "specific_risk": False}),
        missing(pieces={"exposure": False, "specific_return": False, "specific_risk": True}),
    ]:
        assert guard.classify_missing(modified)["reason"] == "unknown_reason"


def test_unknown_reason_is_warning_not_new_hard_gate():
    row = missing(listed="2010-01-01")
    result = guard.evaluate_day(envelope(), daily(), [row], interfaces())
    assert result["passes_coverage_guard"] and result["unknown_reason_rows"]
    assert result["warnings"] == ["unknown_reason"] and not result["reject_reasons"]
    assert not result["next_day_recovery_used_for_decision"]


@pytest.mark.parametrize("piece", guard.INTERFACES)
def test_any_whole_interface_empty_is_rejected(piece):
    result = guard.evaluate_day(envelope(), daily(), [missing()], interfaces(**{piece: False}))
    assert (
        not result["passes_coverage_guard"]
        and "interface_empty:" + piece in result["reject_reasons"]
    )


def test_identity_status_is_separate_from_general_unknown():
    row = missing(status="sdk_filtered", pieces=dict.fromkeys(guard.INDIVIDUAL, False))
    result = guard.evaluate_day(envelope(), daily(), [row], interfaces())
    assert result["existing_identity_anomalies"] and not result["unknown_reason_rows"]
    assert result["existing_contracts_still_required"] and not result["publication_authorized"]


def test_event_evidence_is_exact_and_causality_cannot_be_guessed():
    row = missing(listed="2010-01-01")
    event = {
        "kind": "suspension",
        "day": row["day"],
        "symbol": row["target_symbol"],
        "reference": "accepted-event-observation",
        "sha256": "a" * 64,
        "explains_missing": True,
    }
    assert guard.classify_missing(row, [event])["reason"] == "suspension_with_evidence"
    for change in [
        {"explains_missing": False},
        {"day": "2020-01-03"},
        {"symbol": "000002.SZ"},
        {"sha256": ""},
        {"reference": ""},
    ]:
        assert guard.classify_missing(row, [{**event, **change}])["reason"] == "unknown_reason"
    other = {**event, "kind": "code_change"}
    assert guard.classify_missing(row, [event, other])["reason"] == "unknown_reason"


def test_coverage_accounting_duplicate_and_full_code_checks():
    row = missing()
    result = guard.evaluate_day(envelope(), daily(absent=2), [row], interfaces())
    assert "coverage_accounting_mismatch" in result["reject_reasons"]
    with pytest.raises(ValueError, match="Duplicate missing"):
        guard.evaluate_day(envelope(), daily(absent=2), [row, row], interfaces())
    bad = copy.deepcopy(row)
    bad["target_symbol"] = "000001.SH"
    with pytest.raises(ValueError, match="conflicting full"):
        guard.classify_missing(bad)


def test_month_counts_missing_security_days_and_unique_instruments_and_deduplicates():
    rows = [missing(), missing(day="2020-01-03", listed="2010-01-01", run="r2")]
    attrs = [guard.classify_missing(row) for row in rows]
    days = [daily(), daily(day="2020-01-03", run="r2")]
    result = guard.monthly_summary(days + days, attrs + attrs)[0]
    assert result["model_days"] == 2 and result["missing_security_days"] == 2
    assert result["unique_missing_instruments"] == 1
    assert result["reason_metrics"]["ipo_first_day_missing_specific_return"] == {
        "missing_security_days": 1,
        "unique_missing_instruments": 1,
    }
    assert result["reason_metrics"]["unknown_reason"] == {
        "missing_security_days": 1,
        "unique_missing_instruments": 1,
    }
    with pytest.raises(ValueError, match="Conflicting missing"):
        guard.monthly_summary(days, attrs + [{**attrs[0], "reason": "unknown_reason"}])


def test_baseline_uses_observed_max_three_not_p99_two_and_audits_recovery_separately():
    ledger = []
    records = []
    for model in guard.MODELS:
        for index in range(100):
            day = f"2020-{index // 28 + 1:02d}-{index % 28 + 1:02d}"
            count = 3 if index == 0 else 2
            ledger.append(daily(day=day, n=5164, absent=count, model=model, run=day))
            for number in range(count):
                records.append(
                    missing(
                        day=day,
                        symbol=f"{number + 1:06d}.SZ",
                        listed=day,
                        model=model,
                        run=day,
                    )
                )
    result = guard.derive_baseline(ledger, records)
    for model in guard.MODELS:
        env = result["envelopes"][model]
        assert env["max_missing_count"] == 3 and env["p99_missing_count"] == 2
        assert env["max_missing_fraction"] == {"numerator": 3, "denominator": 5164}
        assert env["unknown_reason_is_rejection_threshold"] is False
        assert guard.allowed_missing(5164, env) == 3
    assert not result["unknown"]
    assert all(not row["used_for_runtime_gate"] for row in result["next_day_audit"])
    assert Counter(row["reason"] for row in result["attribution"]) == {
        "ipo_first_day_missing_specific_return": 603
    }


def test_invalid_or_unmatched_baseline_rows_do_not_define_thresholds():
    row = missing()
    with pytest.raises(ValueError, match="invalid or duplicate"):
        guard.derive_baseline([daily(), daily()], [row])
    with pytest.raises(ValueError, match="do not match"):
        guard.derive_baseline([daily()], [{**row, "run_id": "other"}])
    with pytest.raises(ValueError, match="does not reconcile"):
        guard.derive_baseline([daily(absent=2)], [row])


def test_approved_baseline_file_and_payload_are_immutable(tmp_path):
    import json

    payload = {
        "schema_version": 1,
        "formula": "min(max_missing_count,ceil(candidate*max_missing_fraction))",
        "unknown_reason_is_rejection_threshold": False,
        "models": {model: envelope(model) for model in guard.MODELS},
    }
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(payload))
    baseline = guard.ValidatedCoverageBaseline.load(path, guard.file_hash(path))
    baseline.verify()
    with pytest.raises(ValueError, match="SHA-256 differs"):
        guard.ValidatedCoverageBaseline.load(path, "a" * 64)
    baseline.payload["models"]["v1"]["max_missing_count"] = 4
    with pytest.raises(ValueError, match="Frozen coverage baseline changed"):
        baseline.verify()


def test_loaded_payload_must_match_the_approved_file_even_if_constructed_directly(tmp_path):
    import json

    payload = {
        "schema_version": 1,
        "formula": "min(max_missing_count,ceil(candidate*max_missing_fraction))",
        "unknown_reason_is_rejection_threshold": False,
        "models": {model: envelope(model) for model in guard.MODELS},
    }
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(payload))
    forged = copy.deepcopy(payload)
    forged["models"]["v1"]["max_missing_count"] = 4
    baseline = guard.ValidatedCoverageBaseline(
        path, guard.file_hash(path), forged, guard.semantic_hash(forged)
    )
    with pytest.raises(ValueError, match="Frozen coverage baseline changed"):
        baseline.verify()
