"""有界准入、逐值比较及首次配额恢复确认屏障的离线回归。"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest


spec = importlib.util.spec_from_file_location(
    "approved_history_runner_tested", Path(__file__).with_name("run.py")
)
assert spec is not None and spec.loader is not None
runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)


def test_monthly_plan_uses_candidate_then_each_actual_month_first_day():
    days = [str(value.date()) for value in pd.date_range("2011-04-01", "2023-12-31", freq="B")]
    selected = runner.monthly_days(days)
    assert len(selected) == 153
    assert selected[:2] == ["2011-04-28", "2011-05-02"]
    assert selected[-1] == "2023-12-01"
    with pytest.raises(ValueError, match="153"):
        runner.monthly_days([value for value in days if not value.startswith("2019-10")])


def test_duplicate_old_target_cannot_replace_missing_seventh_observation():
    rows = [{"model": "v1", "day": "2010-01-04"}] + [
        {"model": model, "day": day}
        for model in runner.MODELS
        for day in ("2014-01-06", "2017-01-04")
    ]
    runner.verify_seven_targets(rows)
    rows[-1] = rows[0]
    with pytest.raises(ValueError, match="unique"):
        runner.verify_seven_targets(rows)


@pytest.mark.parametrize("piece", ["exposure", "specific_risk", "specific_return"])
def test_piecewise_comparison_preserves_ipo_values_and_records_unobserved_additions(piece):
    codes = {"603444.XSHG": "603444.SH", "300586.XSHE": "300586.SZ"}
    newer = {**codes, "600680.XSHG": "600680.SH"}
    if piece == "exposure":
        old = pd.DataFrame([[1.0], [2.0]], index=list(codes), columns=["size"])
        new = pd.DataFrame([[1.0], [2.0], [3.0]], index=list(newer), columns=["size"])
    else:
        old = pd.DataFrame([[1.0, 2.0]], index=[date(2017, 1, 4)], columns=list(codes))
        new = pd.DataFrame([[1.0, 2.0, 3.0]], index=old.index, columns=list(newer))
    result = runner.compare_piece(old, new, codes, newer, piece)
    assert result["common_values_equal"]
    assert result["compared_values"] == 2
    assert result["old_not_observed_now_returned"] == ["600680.SH"]
    new.iloc[0, 0] = 1.01
    with pytest.raises(ValueError, match="values changed"):
        runner.compare_piece(old, new, codes, newer, piece)


def test_factor_axis_switch_is_rejected_even_when_each_day_is_individually_valid():
    rows = [
        {
            "model": "v2",
            "day": "2011-04-28",
            "factor_set_sha256": "a",
            "industry_axis_sha256": "approved",
        },
        {
            "model": "v2",
            "day": "2011-05-03",
            "factor_set_sha256": "b",
            "industry_axis_sha256": "changed",
        },
    ]
    changes = runner.axis_changes(rows, "approved")
    assert len(changes) == 1
    assert changes[0]["previous"]["day"] == "2011-04-28"
    assert changes[0]["current"]["day"] == "2011-05-03"


def test_lookahead_cannot_become_formal_target():
    job = object.__new__(runner.HistoryRun)
    with pytest.raises(ValueError, match="helper cannot"):
        job.target("formal_raw", "v2", "2024-01-02", "production")


@pytest.mark.parametrize("failure", [False, True])
def test_first_successful_resume_always_waits_even_if_after_quota_hits_limit(
    tmp_path, monkeypatch, failure
):
    job = object.__new__(runner.HistoryRun)
    job.root = tmp_path
    job.state_path = tmp_path / "state.json"
    job.client = object()
    job.state = {
        "paused_quota_day": "2026-11-02",
        "quota_day": "2026-11-03",
        "first_resume_before": {"bytes_used": 0, "bytes_limit": 1000},
        "first_resume_in_progress": True,
    }
    runner.save(tmp_path / "quota/2026-11-02-pause.json", {"bytes_used": 970, "bytes_limit": 1000})

    def snapshot(_client):
        assert (
            json.loads(job.state_path.read_text())["status"] == "awaiting_first_resume_confirmation"
        )
        if failure:
            raise ConnectionError("unavailable")
        return {"bytes_used": 1000, "bytes_limit": 1000}

    monkeypatch.setattr(runner, "_quota_snapshot", snapshot)
    with pytest.raises(runner.FirstResumeReviewRequiredError):
        job.first_resume_report(
            "formal_raw/v2/2012-01-04", {"path": "accepted", "sha256": "frozen"}
        )
    assert job.state["status"] == "awaiting_first_resume_confirmation"
    receipt = json.loads((tmp_path / "first-next-day-resume.json").read_text())
    assert receipt["status"] == "awaiting_user_confirmation"
    if failure:
        assert receipt["after_snapshot_error"] == "ConnectionError"
    else:
        assert receipt["after"]["bytes_used"] == 1000


def test_confirmation_wait_does_not_connect_or_collect():
    job = object.__new__(runner.HistoryRun)
    job.state = {"status": "awaiting_first_resume_confirmation"}
    with pytest.raises(runner.FirstResumeReviewRequiredError):
        job.execute()


@pytest.mark.parametrize(
    ("expected_model", "expected_day", "expected_purpose"),
    [
        ("v1", "2011-04-28", "validation"),
        ("v2", "2011-05-03", "validation"),
        ("v2", "2011-04-28", "production"),
    ],
)
def test_cached_valid_report_cannot_be_reused_for_another_ledger_key(
    tmp_path, monkeypatch, expected_model, expected_day, expected_purpose
):
    job = object.__new__(runner.HistoryRun)
    job.options = lambda model, day, purpose: SimpleNamespace(
        identity={"model": model, "purpose": purpose}, variant_id=purpose
    )
    report = {
        "status": "accepted",
        "policy_sha256": runner.APPROVED_POLICY_SHA256,
        "model": "v2",
        "day": "2011-04-28",
        "current_observation": {},
        "next_observation": None,
    }
    path = tmp_path / "assessment.json"
    runner.save(path, report)
    monkeypatch.setattr(
        runner,
        "verify_raw_evidence",
        lambda _proof: {
            "day": "2011-04-28",
            "identity": {"model": "v2", "purpose": "validation"},
            "variant_id": "validation",
            "purpose": "validation",
        },
    )
    with pytest.raises(ValueError, match="ledger key"):
        job.verify_completed(
            {"path": str(path), "sha256": runner.digest(path)},
            model=expected_model,
            day=expected_day,
            purpose=expected_purpose,
        )


def test_month_quality_separates_two_purposes_for_same_model_day(tmp_path):
    report = {
        "model": "v2",
        "day": "2011-04-28",
        "status": "accepted",
        "policy_sha256": runner.APPROVED_POLICY_SHA256,
        "missing": [],
        "current_observation": {},
        "next_observation": None,
        "calendar": None,
    }
    for purpose in ("validation", "production"):
        runner.save(
            tmp_path / "assessments" / purpose / "v2" / "2011-04-28.json",
            {**report, "current_observation": {"purpose": purpose}},
        )
    result = runner.quality_summaries(tmp_path)
    assert set(result["by_purpose"]) == {"validation", "production"}
    assert all(len(rows) == 1 for rows in result["by_purpose"].values())


def test_reassessing_same_day_pending_never_overwrites_earlier_accepted_receipt(
    tmp_path, monkeypatch
):
    job = object.__new__(runner.HistoryRun)
    job.root = tmp_path
    job.calendar = None
    base = {"model": "v2trd", "day": "2011-04-28", "reject_reasons": []}
    accepted = {**base, "status": "accepted"}
    pending = {**base, "status": "pending"}
    decisions = iter([accepted, pending])
    monkeypatch.setattr(runner, "evaluate_delayed_day", lambda *_args, **_kwargs: next(decisions))
    observation = SimpleNamespace(manifest={"purpose": "validation"})
    first = job.assess(observation)
    prior = job.decision_path("validation", first)
    original = runner.digest(prior)
    job.assess(observation)
    assert runner.digest(prior) == original
    assert json.loads(prior.read_text())["status"] == "accepted"
    latest = tmp_path / "assessments/validation/v2trd/2011-04-28.json"
    assert json.loads(latest.read_text())["status"] == "pending"
