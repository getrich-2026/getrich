"""经验覆盖门槛必须先于 DB capture，含旧 raw 的 init 复用。"""

from __future__ import annotations

import json

import pytest
from gr_data.common.paths import RawPaths
from gr_data.common.ricequant_symbol_intervals import (
    HISTORY_SYMBOL_RULES_VERSION,
    symbol_rule_evidence,
)
from gr_data.common.ricequant_universe import build_universe_provider
from gr_data.config.ricequant import RicequantImportOptions
from gr_data.raw.base import RawContext
from test_probe import ProbeClient, coverage_baseline, probe, template


def setup_day(tmp_path, count=4599, missing_count=4, *, ipo=True, none_risk=False):
    day = "2021-12-28"
    codes = [f"{index:06d}.XSHG" for index in range(1, count + 1)]
    missing_codes = set(codes[:missing_count])
    metadata = {
        "instruments": [
            {
                "instrument_id": index,
                "symbol": code.replace(".XSHG", ".SH"),
                "exchange": "XSHG",
                "list_date": day if ipo and code in missing_codes else "2000-01-01",
                "delist_date": None,
                "status": "L",
            }
            for index, code in enumerate(codes, 1)
        ],
        "aliases": [],
    }
    reference = {
        "sdk_mapping": dict(zip(codes, codes, strict=True)),
        "instruments": [
            {"order_book_id": code, "listed_date": row["list_date"], "de_listed_date": "0000-00-00"}
            for code, row in zip(codes, metadata["instruments"], strict=True)
        ],
    }
    provider = build_universe_provider(
        metadata,
        reference,
        universe_policy="listed_cn_a_v2",
        symbol_rules=symbol_rule_evidence(HISTORY_SYMBOL_RULES_VERSION),
    )

    class Client(ProbeClient):
        def risk_piece(self, piece, day, codes, **kwargs):
            if none_risk and piece == "specific_risk":
                self.calls.append((piece, day, tuple(codes)))
                self.used += 1000
                return None
            if piece == "specific_return":
                codes = [code for code in codes if code not in missing_codes]
            return super().risk_piece(piece, day, codes, **kwargs)

    options = probe.options_for_job(template(), {"model": "v1", "start": day, "end": "2021-12-29"})
    return (
        Client(),
        RawContext(RawPaths(tmp_path), {"sleep_between_requests_sec": 0}),
        options,
        provider,
    )


def test_four_ipo_stop_before_capture_and_next_day_and_old_raw_is_guarded(tmp_path):
    client, ctx, options, provider = setup_day(tmp_path)
    baseline = coverage_baseline(tmp_path)
    captures = []
    audits = []

    def persist(audit):
        audits.append(audit)
        probe.persist_coverage_audit(tmp_path / "audit-run", audit)

    state = {"completed": {}, "status": "running"}
    state_path = tmp_path / "state.json"
    with (
        pytest.raises(probe.CoverageGateRejectedError) as error,
        probe.stopped_on_failure(state_path, state),
    ):
        probe.execute_job(
            client,
            ctx,
            options,
            RicequantImportOptions({}),
            provider,
            captures.append,
            coverage_baseline=baseline,
            audit_callback=persist,
        )
    audit = error.value.audit
    assert audit["candidate"] == 4599 and audit["complete"] == 4595
    assert audit["allowed_missing_count"] == 3 and audit["missing_count"] == 4
    assert audit["raw_retained"] and not audit["recognized_batch_completion"]
    assert captures == [] and all(call[1] == "2021-12-28" for call in client.calls)
    persisted = json.loads(state_path.read_text())
    assert persisted["status"] == "stopped_by_coverage_gate" and persisted["completed"] == {}
    manifest = next(tmp_path.glob("ricequant/rq_risk_model/v2/*/2021-12-28/*/manifest.json"))
    original = probe.digest(manifest)
    before = len(client.calls)
    with pytest.raises(probe.CoverageGateRejectedError):
        probe.execute_job(
            client,
            ctx,
            options,
            RicequantImportOptions({}),
            provider,
            captures.append,
            coverage_baseline=baseline,
        )
    assert len(client.calls) == before and probe.digest(manifest) == original and captures == []
    month = json.loads(
        next((tmp_path / "audit-run" / "coverage-monthly").glob("*.json")).read_text()
    )
    rejected = month["rejected_coverage_statistics"][0]
    assert rejected["reason_metrics"]["ipo_first_day_missing_specific_return"] == {
        "missing_security_days": 4,
        "unique_missing_instruments": 4,
    }
    assert month["monthly"] == []


@pytest.mark.parametrize("missing_count", [1, 2, 3])
def test_normal_ipo_one_to_three_are_allowed(tmp_path, missing_count):
    client, ctx, options, provider = setup_day(tmp_path, missing_count=missing_count)
    # 限定单日；新副本仍不改上市边界或过滤名单。
    from dataclasses import replace

    options = replace(options, end_date=options.start_date)
    captures = []
    report = probe.execute_job(
        client,
        ctx,
        options,
        RicequantImportOptions({}),
        provider,
        captures.append,
        coverage_baseline=coverage_baseline(tmp_path),
    )
    assert report["calendar_complete"] and len(captures) == 1
    assert report["coverage_guard_results"][0]["missing_count"] == missing_count
    assert not report["coverage_guard_results"][0]["unknown_reason_rows"]


def test_unknown_single_missing_is_warning_and_monthly_not_rejection(tmp_path):
    from dataclasses import replace

    client, ctx, options, provider = setup_day(tmp_path, count=1000, missing_count=1, ipo=False)
    options = replace(options, end_date=options.start_date)
    root = tmp_path / "audit-run"
    captures = []
    report = probe.execute_job(
        client,
        ctx,
        options,
        RicequantImportOptions({}),
        provider,
        captures.append,
        coverage_baseline=coverage_baseline(tmp_path),
        audit_callback=lambda audit: probe.persist_coverage_audit(root, audit),
    )
    assert len(captures) == 1 and report["coverage_guard_results"][0]["warnings"] == [
        "unknown_reason"
    ]
    month = json.loads(next((root / "coverage-monthly").glob("*.json")).read_text())
    metric = month["monthly"][0]["reason_metrics"]["unknown_reason"]
    assert metric == {"missing_security_days": 1, "unique_missing_instruments": 1}
    assert not month["rejected_days"]


def test_whole_specific_risk_none_stops_at_first_day_before_capture(tmp_path):
    client, ctx, options, provider = setup_day(
        tmp_path, count=1000, missing_count=0, none_risk=True
    )
    captures = []
    with pytest.raises(probe.CoverageGateRejectedError) as error:
        probe.execute_job(
            client,
            ctx,
            options,
            RicequantImportOptions({}),
            provider,
            captures.append,
            coverage_baseline=coverage_baseline(tmp_path),
        )
    assert "interface_empty:specific_risk" in error.value.audit["reject_reasons"]
    assert all(call[1] == "2021-12-28" for call in client.calls) and captures == []
    assert error.value.audit["raw_evidence"]["failed_receipts"]


def test_missing_or_changed_baseline_is_rejected_before_sdk(tmp_path):
    class NeverClient:
        def get_quota(self):
            raise AssertionError("SDK must not be touched")

    with pytest.raises(ValueError, match="baseline is required"):
        probe.execute_job(NeverClient(), RawContext(RawPaths(tmp_path)), None, None, None, None)
    with pytest.raises(ValueError, match="Explicit coverage baseline"):
        probe.verified_baseline({}, None, None)
    baseline = coverage_baseline(tmp_path)
    baseline.path.write_text("{}")
    with pytest.raises(ValueError, match="Frozen coverage baseline changed"):
        probe.execute_job(
            NeverClient(),
            RawContext(RawPaths(tmp_path)),
            None,
            None,
            None,
            None,
            coverage_baseline=baseline,
        )
