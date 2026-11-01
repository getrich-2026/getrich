"""历史探测边界、旧规则兼容与 raw 失败证据；不接真实服务。"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from gr_data.common.paths import RawPaths
from gr_data.common.ricequant_specs import RqConfigurationError, semantic_hash
from gr_data.common.ricequant_symbol_intervals import (
    HISTORY_SYMBOL_RULES_VERSION,
    interval_source_symbol,
    resolve_symbol_intervals,
    symbol_rule_evidence,
    symbol_rule_hash,
)
from gr_data.common.ricequant_universe import build_universe_provider
from gr_data.config.ricequant import RicequantImportOptions
from gr_data.config.ricequant_risk import parse_risk_options
from gr_data.raw.base import RawContext


spec = importlib.util.spec_from_file_location(
    "ricequant_history_probe", Path(__file__).with_name("probe.py")
)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


def template():
    return {
        "selected": True,
        "permission_confirmed": True,
        "model": "v1",
        "industry_mapping": "sws_2021",
        "start_date": "2024-01-02",
        "end_date": "2024-01-03",
        "universe_policy": "listed_cn_a_v2",
        "purpose": "production",
        "source_units": {
            "factor_return": "dec_daily",
            "specific_return": "dec_daily",
            "covariance": "dec2_annual",
            "specific_risk": "dec_annual",
        },
        "units_evidence": "synthetic-test-only",
    }


def test_probe_is_explicit_validation_without_relaxing_production():
    job = {"model": "v1", "start": "2010-01-04", "end": "2010-01-04"}
    options = probe.options_for_job(template(), job)
    assert options.purpose == "validation" and options.historical_probe
    assert options.symbol_rules_version == HISTORY_SYMBOL_RULES_VERSION
    with pytest.raises(RqConfigurationError):
        parse_risk_options({**template(), "start_date": job["start"], "end_date": job["end"]})
    with pytest.raises(RqConfigurationError):
        parse_risk_options(
            {**template(), "start_date": job["start"], "end_date": job["end"]},
            historical_probe=True,
        )
    for bad in ["2009-12-31", "2024-01-01"]:
        with pytest.raises(RqConfigurationError):
            probe.options_for_job(template(), {**job, "start": bad, "end": bad})
    old = parse_risk_options(template())
    assert old.symbol_rules_version == "cn_stock_code_intervals_v1"
    assert "historical_probe" not in old.identity
    assert options.variant_id != old.variant_id


def test_old_rules_keep_exact_evidence_and_hash():
    old = symbol_rule_evidence()
    assert old["version"] == "cn_stock_code_intervals_v1"
    assert len(old["rules"]) == 1
    assert old["rules"][0]["old_source_symbol"] == "300114.SZ"
    assert symbol_rule_hash() == semantic_hash(old)
    new = symbol_rule_evidence(HISTORY_SYMBOL_RULES_VERSION)
    assert len(new["rules"]) == 5 and new["rules"][0] == old["rules"][0]
    new["rules"].clear()
    assert len(symbol_rule_evidence(HISTORY_SYMBOL_RULES_VERSION)["rules"]) == 5


@pytest.mark.parametrize("rule", symbol_rule_evidence(HISTORY_SYMBOL_RULES_VERSION)["rules"])
def test_effective_dates_request_old_code_until_switch(rule):
    old, new, effective = (
        rule["old_source_symbol"],
        rule["new_source_symbol"],
        date.fromisoformat(rule["effective_date"]),
    )
    metadata = {
        "instruments": [
            {
                "instrument_id": 77,
                "symbol": new,
                "exchange": "XSHG" if new.endswith(".SH") else "XSHE",
                "list_date": "1990-01-01",
                "delist_date": None,
                "status": "L",
            }
        ],
        "aliases": [{"source": "tushare", "source_symbol": old, "instrument_id": 77}],
    }
    resolved = resolve_symbol_intervals(metadata, HISTORY_SYMBOL_RULES_VERSION)
    assert interval_source_symbol(77, new, str(effective - timedelta(days=1)), resolved)[0] == old
    assert interval_source_symbol(77, new, str(effective), resolved)[0] == new

    def obid(code):
        return code.replace(".SZ", ".XSHE").replace(".SH", ".XSHG")

    reference = {
        "instruments": [
            {
                "order_book_id": obid(old),
                "listed_date": "1990-01-01",
                "de_listed_date": str(effective),
            },
            {
                "order_book_id": obid(new),
                "listed_date": "1990-01-01",
                "de_listed_date": "0000-00-00",
            },
        ],
        "sdk_mapping": {obid(old): obid(old), obid(new): obid(new)},
    }
    provider = build_universe_provider(
        metadata,
        reference,
        universe_policy="listed_cn_a_v2",
        symbol_rules=symbol_rule_evidence(HISTORY_SYMBOL_RULES_VERSION),
    )
    for day, expected in [(effective - timedelta(days=1), old), (effective, new)]:
        row = provider(str(day))["candidates"][0]
        assert row["request_code"] == obid(expected) and row["status"] is None
        assert row["evidence"]["symbol_interval"]["evidence_url"].startswith("https://")
    reference["sdk_mapping"][obid(old)] = obid(new)
    filtered = build_universe_provider(
        metadata,
        reference,
        universe_policy="listed_cn_a_v2",
        symbol_rules=symbol_rule_evidence(HISTORY_SYMBOL_RULES_VERSION),
    )
    row = filtered(str(effective - timedelta(days=1)))["candidates"][0]
    assert row["status"] == "sdk_filtered" and row["request_code"] is None


def test_alias_inventory_never_guesses_new_identity():
    snapshot = {
        "instruments": [{"instrument_id": 1, "symbol": "600001.SH"}],
        "aliases": [{"instrument_id": 1, "source": "tushare", "source_symbol": "T600001.SH"}],
    }
    inventory = probe.alias_inventory(snapshot)
    assert inventory["new_aliases_created"] == 0
    assert inventory["other_candidates"] == [
        {
            "old_symbol": "T600001.SH",
            "canonical_symbol": "600001.SH",
            "status": "needs_identity_and_date_review",
        }
    ]
    assert not inventory["exhaustive_historical_code_change_inventory"]


def test_plan_is_probe_only_and_covers_requested_periods():
    plan = probe.make_plan()
    assert len(plan["jobs"]) == 27
    assert (
        not plan["formal_collection_authorized"] and not plan["working_database_ingest_authorized"]
    )
    for model in probe.MODELS:
        jobs = [job for job in plan["jobs"] if job["model"] == model]
        assert {job["start"][:4] for job in jobs if job["key"].startswith("representative")} == {
            "2010",
            "2014",
            "2017",
            "2020",
            "2023",
        }
        assert any(job["start"] == "2023-01-01" and job["end"] == "2023-01-31" for job in jobs)
        assert {job["key"] for job in jobs if job["key"].startswith("industry")} == {
            "industry-2021-11",
            "industry-2021-12-mid",
            "industry-2021-12",
        }


def test_probe_cannot_start_before_full_replay_acceptance(tmp_path):
    acceptance = tmp_path / "acceptance.json"
    acceptance.write_text(json.dumps({"status": "running", "verified_model_days": 247}))
    gate = {
        "stage": "probe_only",
        "plan_sha256": "p",
        "source_commit": "c",
        "current_replay_acceptance_path": str(acceptance),
        "current_replay_acceptance_sha256": probe.digest(acceptance),
    }
    with pytest.raises(ValueError, match="not fully accepted"):
        probe.verify_start_gate(gate, "p", "c")
    acceptance.write_text(json.dumps({"status": "completed", "verified_model_days": 2028}))
    gate["current_replay_acceptance_sha256"] = probe.digest(acceptance)
    probe.verify_start_gate(gate, "p", "c")
    with pytest.raises(ValueError, match="identity differs"):
        probe.verify_start_gate(gate, "different", "c")


def test_industry_axis_change_is_reported_without_approving_continuity():
    observations = [
        {
            "day": day,
            "coverage_counts": {"complete": 10, "candidate": 10},
            "industry_factors": industries,
            "industry_axis_hash": semantic_hash(industries),
        }
        for day, industries in [("2021-11-26", ["银行"]), ("2021-11-29", ["银行", "美容护理"])]
    ]
    report = {
        "model": "v1",
        "observations": observations,
        "failures": [],
        "account_counter_delta": 200,
    }
    summary = probe.summarize_reports([report])
    result = summary["models"]["v1"]
    assert result["earliest_complete_sample"] == "2021-11-26"
    assert result["industry_axis_changes_between_samples"][0]["first_sample"] == "2021-11-29"
    assert (
        not result["industry_semantic_continuity_confirmed"]
        and not result["full_year_start_confirmed"]
    )
    assert not summary["formal_collection_authorized"]


class ProbeClient:
    def __init__(self, *, invalid_covariance=False, missing_symbol=None):
        self.calls = []
        self.used = 0
        self.invalid_covariance = invalid_covariance
        self.missing_symbol = missing_symbol

    def get_quota(self):
        return {"bytes_limit": 100000000, "bytes_used": self.used}

    def get_trading_dates(self, start, end):
        return list(pd.bdate_range(start, end).date)

    def risk_piece(self, piece, day, codes, *, model, industry_mapping):
        import numpy as np
        from gr_data.raw.ricequant.risk_shapes import STYLE_FACTORS

        self.calls.append((piece, day, tuple(codes)))
        self.used += 1000
        factors = sorted(STYLE_FACTORS[model] | {"comovement", "银行"})
        if piece == "factor_return":
            return pd.DataFrame(
                [[0.001] * len(factors)], index=pd.DatetimeIndex([day]), columns=factors
            )
        if piece == "covariance":
            value = -0.01 if self.invalid_covariance else 0.01
            return pd.DataFrame(np.eye(len(factors)) * value, index=factors, columns=factors)
        codes = [code for code in codes if code != self.missing_symbol]
        if piece == "exposure":
            index = pd.MultiIndex.from_product(
                [codes, [pd.Timestamp(day)]], names=["order_book_id", "date"]
            )
            frame = pd.DataFrame(0.1, index=index, columns=factors)
            frame["comovement"] = frame["银行"] = 1.0
            return frame
        value = 0.2 if piece == "specific_risk" else 0.001
        return pd.DataFrame([[value] * len(codes)], index=pd.DatetimeIndex([day]), columns=codes)


def probe_provider():
    metadata = {
        "instruments": [
            {
                "instrument_id": index,
                "symbol": code,
                "exchange": "XSHE",
                "list_date": "1991-01-01",
                "delist_date": None,
                "status": "L",
            }
            for index, code in enumerate(["000001.SZ", "000002.SZ"], 1)
        ],
        "aliases": [],
    }
    codes = ["000001.XSHE", "000002.XSHE"]
    reference = {
        "instruments": [
            {"order_book_id": code, "listed_date": "1991-01-01", "de_listed_date": "0000-00-00"}
            for code in codes
        ],
        "sdk_mapping": dict(zip(codes, codes, strict=True)),
    }
    return build_universe_provider(
        metadata,
        reference,
        universe_policy="listed_cn_a_v2",
        symbol_rules=symbol_rule_evidence(HISTORY_SYMBOL_RULES_VERSION),
    )


def test_real_raw_path_hashes_calendar_coverage_and_idempotence(tmp_path):
    options = probe.options_for_job(
        template(), {"model": "v1", "start": "2010-01-04", "end": "2010-01-06"}
    )
    client = ProbeClient()
    ctx = RawContext(RawPaths(tmp_path), {"sleep_between_requests_sec": 0})
    captures = []
    report = probe.execute_job(
        client, ctx, options, RicequantImportOptions({}), probe_provider(), captures.append
    )
    assert report["calendar_complete"] and report["all_candidates_complete"]
    assert len(captures) == 3 and len(report["observations"]) == 3
    assert len(client.calls) == 15 and report["account_counter_delta"] == 15000
    for row in report["observations"]:
        assert row["coverage_counts"]["candidate"] == row["coverage_counts"]["complete"] == 2
        assert len(row["files"]) == 5 and len(row["manifest_hash"]) == 64
    replay = probe.execute_job(
        client, ctx, options, RicequantImportOptions({}), probe_provider(), captures.append
    )
    assert replay["calendar_complete"] and len(client.calls) == 15
    assert replay["account_counter_delta"] == 0


def test_missing_candidate_is_not_removed_to_claim_full_coverage(tmp_path):
    options = probe.options_for_job(
        template(), {"model": "v1", "start": "2010-01-04", "end": "2010-01-04"}
    )
    ctx = RawContext(RawPaths(tmp_path), {"sleep_between_requests_sec": 0})
    report = probe.execute_job(
        ProbeClient(missing_symbol="000002.XSHE"),
        ctx,
        options,
        RicequantImportOptions({}),
        probe_provider(),
        lambda manifest: None,
    )
    assert report["calendar_complete"] and not report["all_candidates_complete"]
    assert report["observations"][0]["coverage_counts"]["candidate"] == 2
    assert report["observations"][0]["coverage_counts"]["complete"] == 1


def test_invalid_numeric_data_retains_failed_receipt_and_never_publishes(tmp_path):
    options = probe.options_for_job(
        template(), {"model": "v1", "start": "2010-01-04", "end": "2010-01-04"}
    )
    ctx = RawContext(RawPaths(tmp_path), {"sleep_between_requests_sec": 0})
    report = probe.execute_job(
        ProbeClient(invalid_covariance=True),
        ctx,
        options,
        RicequantImportOptions({}),
        probe_provider(),
        lambda manifest: None,
    )
    assert not report["calendar_complete"] and not report["observations"]
    receipt = report["failures"][0]["receipts"][0]
    assert (
        Path(receipt["path"]).is_file() and probe.digest(Path(receipt["path"])) == receipt["sha256"]
    )
    assert not list(tmp_path.glob("ricequant/rq_risk_model/v2/*/2010-01-04/*/manifest.json"))


def test_database_cluster_oid_and_name_are_pinned_before_capture():
    class Connection:
        committed = False

        def execute(self, query):
            assert "pg_control_system()" in query and "pg_database" in query
            return self

        def fetchone(self):
            return ("getrich_rq_history_probe", "cluster-1", 123)

        def commit(self):
            self.committed = True

    gate = {
        "evidence_database": "getrich_rq_history_probe",
        "evidence_system_identifier": "cluster-1",
        "evidence_database_oid": 123,
    }
    connection = Connection()
    probe.verify_evidence_database(connection, gate)
    assert connection.committed
    for key, value in [
        ("evidence_database", "getrich"),
        ("evidence_system_identifier", "other"),
        ("evidence_database_oid", 456),
    ]:
        with pytest.raises(ValueError, match="identity differs"):
            probe.verify_evidence_database(connection, {**gate, key: value})


def test_input_binding_rejects_changed_metadata_reference_and_templates(tmp_path):
    for name in ["metadata.json", "reference.json", "v1.yaml", "plan.json"]:
        path = tmp_path / name
        path.write_text("first")
        state = {}
        probe.bind_input(path, state)
        probe.bind_input(path, state)
        path.write_text("changed")
        with pytest.raises(ValueError, match="Frozen probe input changed"):
            probe.bind_input(path, state)
    unbound = tmp_path / "metadata-external.json"
    unbound.write_text("new")
    with pytest.raises(ValueError, match="Frozen probe input changed"):
        probe.bind_input(unbound, {}, expected="wrong-hash")


def test_quota_normalization_excludes_zero_reset_and_reused_windows():
    reports = [
        {
            "account_counter_delta": delta,
            "newly_fetched_days": days,
            "newly_fetched_candidate_days": candidates,
        }
        for delta, days, candidates in [
            (2000, ["a", "b"], 200),
            (6000, ["c", "d"], 200),
            (0, ["e"], 100),
            (None, ["f"], 100),
            (300, [], 0),
        ]
    ]
    estimate = probe.quota_estimate(reports)
    assert estimate["observed_bytes_per_new_model_day_range"] == [1000, 3000]
    assert estimate["observed_bytes_per_candidate_day_range"] == [10, 30]
    assert (
        estimate["measured_positive_windows"] == 2
        and estimate["unmeasurable_or_reused_windows"] == 3
    )
    assert not estimate["zero_delta_means_free"] and not estimate["exact_request_cost"]


def test_ops_source_hash_head_and_cleanliness_are_independently_pinned(tmp_path, monkeypatch):
    from types import SimpleNamespace

    script = tmp_path / "probe.py"
    script.write_text("original")
    gate = {"source_head_commit": "a" * 40, "probe_sha256": probe.digest(script)}
    status = ""
    head = "a" * 40

    def git_result(command, **kwargs):
        return SimpleNamespace(stdout=head if command[1] == "rev-parse" else status)

    monkeypatch.setattr(probe.subprocess, "run", git_result)
    probe.verify_source_gate(gate, tmp_path, script)
    script.write_text("modified")
    with pytest.raises(ValueError, match="runner hash changed"):
        probe.verify_source_gate(gate, tmp_path, script)
    script.write_text("original")
    status = " M packages/gr-data/ops/ricequant_history_probe/probe.py"
    with pytest.raises(ValueError, match="uncommitted changes"):
        probe.verify_source_gate(gate, tmp_path, script)
    status = ""
    head = "b" * 40
    with pytest.raises(ValueError, match="HEAD changed"):
        probe.verify_source_gate(gate, tmp_path, script)


@pytest.mark.parametrize("error_name", ["BudgetDeferredError", "PermanentError", "ConnectionError"])
def test_request_boundary_failures_stop_batch_and_do_not_become_missing_days(tmp_path, error_name):
    from gr_data.common.retry import PermanentError
    from gr_data.common.ricequant_specs import BudgetDeferredError

    error = {
        "BudgetDeferredError": BudgetDeferredError,
        "PermanentError": PermanentError,
        "ConnectionError": ConnectionError,
    }[error_name]

    class FailedClient(ProbeClient):
        def risk_piece(self, *args, **kwargs):
            raise error("synthetic-request-boundary")

    options = probe.options_for_job(
        template(), {"model": "v1", "start": "2010-01-04", "end": "2010-01-06"}
    )
    ctx = RawContext(RawPaths(tmp_path), {"sleep_between_requests_sec": 0, "max_retries": 1})
    state = {"status": "running"}
    state_path = tmp_path / "state.json"
    with pytest.raises(error), probe.stopped_on_failure(state_path, state):
        probe.execute_job(
            FailedClient(),
            ctx,
            options,
            RicequantImportOptions({}),
            probe_provider(),
            lambda manifest: None,
        )
    persisted = json.loads(state_path.read_text())
    assert persisted["status"] == "stopped" and persisted["error_type"] == error_name


def test_capture_evidence_failure_stops_instead_of_claiming_historical_gap(tmp_path):
    from gr_data.common.ricequant_specs import ContractViolationError

    def failed_capture(manifest):
        raise ContractViolationError("synthetic-capture-conflict")

    options = probe.options_for_job(
        template(), {"model": "v1", "start": "2010-01-04", "end": "2010-01-04"}
    )
    ctx = RawContext(RawPaths(tmp_path), {"sleep_between_requests_sec": 0})
    with pytest.raises(probe.CaptureEvidenceError):
        probe.execute_job(
            ProbeClient(),
            ctx,
            options,
            RicequantImportOptions({}),
            probe_provider(),
            failed_capture,
        )
    assert list(tmp_path.glob("ricequant/rq_risk_model/v2/*/2010-01-04/*/manifest.json"))


def test_raw_root_is_absolute_and_approved_before_sdk_initialization(tmp_path):
    first = tmp_path / "first"
    gate = {"raw_parquet_root": str(first)}
    assert probe.verify_raw_root(str(first), gate) == first.resolve()
    with pytest.raises(ValueError, match="raw parquet root differs"):
        probe.verify_raw_root(str(tmp_path / "second"), gate)
    with pytest.raises(ValueError, match="absolute path"):
        probe.verify_raw_root("relative", gate)


def test_unreviewed_real_code_changes_block_affected_dates_before_requests():
    snapshot = {
        "instruments": [
            {
                "instrument_id": 1,
                "symbol": "601607.SH",
                "list_date": "1994-03-24",
                "delist_date": None,
            },
            {
                "instrument_id": 2,
                "symbol": "601360.SH",
                "list_date": "2012-01-16",
                "delist_date": None,
            },
        ],
        "aliases": [],
    }
    for day, expected_old in [
        ("2010-01-04", "600849.SH"),
        ("2014-01-06", "601313.SH"),
        ("2017-01-04", "601313.SH"),
    ]:
        issues = probe.unresolved_identity_issues(snapshot, {"start": day, "end": day})
        assert len(issues) == 1 and issues[0]["old_symbol"] == expected_old
        assert issues[0]["status"] == "blocked_identity" and issues[0]["new_aliases_created"] == 0
    for day in ["2020-01-06", "2023-01-04"]:
        assert not probe.unresolved_identity_issues(snapshot, {"start": day, "end": day})
    assert not snapshot["aliases"]


def test_identity_blocked_segment_is_not_reported_as_model_data_missing():
    blocked = {
        "model": "v1",
        "status": "blocked_identity",
        "identity_blockers": [{"old_symbol": "600849.SH"}],
        "observations": [],
        "failures": [],
        "account_counter_delta": None,
    }
    summary = probe.summarize_reports([blocked])
    assert summary["models"]["v1"]["identity_blocked_segments"]
    assert not summary["models"]["v1"]["failed_days"]
    assert summary["models"]["v1"]["earliest_complete_sample"] is None


def test_reviewed_alias_registration_is_required_to_unblock_old_code_dates():
    snapshot = {
        "instruments": [
            {
                "instrument_id": 1,
                "symbol": "601607.SH",
                "list_date": "1994-03-24",
                "delist_date": None,
            },
            {
                "instrument_id": 2,
                "symbol": "601360.SH",
                "list_date": "2012-01-16",
                "delist_date": None,
            },
        ],
        "aliases": [],
    }
    job = {"start": "2010-01-04", "end": "2017-01-04"}
    assert len(probe.unresolved_identity_issues(snapshot, job)) == 2
    snapshot["aliases"] = [
        {"source": "tushare", "source_symbol": "600849.SH", "instrument_id": 1},
        {"source": "tushare", "source_symbol": "601313.SH", "instrument_id": 2},
    ]
    assert not probe.unresolved_identity_issues(snapshot, job)
    snapshot["aliases"][0]["instrument_id"] = 2
    assert probe.unresolved_identity_issues(snapshot, job)[0]["old_symbol"] == "600849.SH"


def test_shanghai_pharma_absorbed_companies_keep_separate_identities():
    metadata = {
        "instruments": [
            {
                "instrument_id": iid,
                "symbol": code,
                "exchange": "XSHG",
                "list_date": "1994-03-24",
                "delist_date": "2010-02-12" if iid != 1 else None,
                "status": "L",
            }
            for iid, code in [(1, "601607.SH"), (2, "600607.SH"), (3, "600842.SH")]
        ],
        "aliases": [{"source": "tushare", "source_symbol": "600849.SH", "instrument_id": 1}],
    }
    rules = resolve_symbol_intervals(metadata, HISTORY_SYMBOL_RULES_VERSION)
    assert set(rules) == {1}
    assert interval_source_symbol(1, "601607.SH", "2010-01-04", rules)[0] == "600849.SH"
    assert interval_source_symbol(2, "600607.SH", "2010-01-04", rules)[0] == "600607.SH"
    assert interval_source_symbol(3, "600842.SH", "2010-01-04", rules)[0] == "600842.SH"
    assert interval_source_symbol(1, "601607.SH", "2010-03-05", rules)[0] == "601607.SH"
    assert metadata["aliases"] == [
        {"source": "tushare", "source_symbol": "600849.SH", "instrument_id": 1}
    ]
