from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml


spec = importlib.util.spec_from_file_location(
    "monthly", Path(__file__).with_name("run_monthly_accounts.py")
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class FakeRuntime:
    def __init__(self, variants):
        self.variants = variants
        self.calls = []
        self.fail = {}
        self.gaps = set()
        self.typed_budget = False
        self.high_after = False
        self.quota_calls = 0
        self.changed_after_raw = False
        self.audit_fail = False
        self.force_exit4 = False
        self.bad_gap = False

    def check_version(self):
        if self.changed_after_raw and self.calls:
            return "different"
        return m.IMPORTER_VERSION

    def calendar(self):
        return ["2024-01-30", "2024-01-31", "2024-02-01", str(m.END)]

    def quota(self):
        self.quota_calls += 1
        return {
            "bytes_used": 950 if self.high_after and self.quota_calls > 1 else 20,
            "bytes_limit": 1000,
            "observed_at": "2026-10-23T01:00:00+00:00",
        }

    def command(self, phase, config, month, log):
        opts = yaml.safe_load(config.read_text())["providers"]["ricequant"]["risk_model"]
        key = (opts["start_date"], opts["model"])
        self.calls.append((phase, *key))
        assert month == key[0][:7]
        return self.fail.get(
            (phase, *key), 4 if phase == "ingest" and (key in self.gaps or self.force_exit4) else 0
        )

    def budget_failure(self, *_):
        return self.typed_budget

    def bundle(self, config):
        opts = yaml.safe_load(config.read_text())["providers"]["ricequant"]["risk_model"]
        day, model = opts["start_date"], opts["model"]
        rows = []
        for iid in range(1, 21):
            gap = iid == 20 and (day, model) in self.gaps
            rows.append(
                {
                    "instrument_id": iid,
                    "canonical_symbol": f"{iid:06}.SZ",
                    "request_code": f"{iid:06}.XSHE",
                    "status": "partial_bundle" if gap else "included",
                    "pieces": {"exposure": True, "specific_risk": True, "specific_return": not gap},
                    "evidence": {
                        "canonical": {"list_date": "1990-01-01" if self.bad_gap else day},
                        "supplier": [{"listed_date": day}],
                    },
                }
            )
        manifest = {
            "day": day,
            "variant_id": self.variants[model],
            "purpose": "production",
            "observation_id": "a" * 32,
            "coverage": rows,
            "coverage_counts": {
                "candidate": 20,
                "complete": sum(r["status"] == "included" for r in rows),
            },
            "universe": {"unresolved": []},
        }
        return manifest, None

    def audit(self, model, directory, output, log):
        manifest, _ = self.bundle(directory / f"{model}.yaml")
        gaps = [r["instrument_id"] for r in manifest["coverage"] if r["status"] != "included"]
        eligible = not gaps
        audit = {
            "status": "passed",
            "model": model,
            "trading_day": manifest["day"],
            "variant_id": self.variants[model],
            "observation_id": manifest["observation_id"],
            "continuation_allowed": True,
            "next_day_pending_instrument_ids": gaps,
            "coverage_counts": manifest["coverage_counts"],
            "run_id": "run",
            "quality": {"warnings": [], "covariance": {"warnings": []}},
            "etl_warning_counts": [int(bool(gaps))],
            "special_checks": {},
            "import_evidence": {
                "status": "passed",
                "importer_version": m.IMPORTER_VERSION,
                "publication_gate": {
                    "eligible": eligible,
                    "reasons": [] if eligible else ["complete_coverage_below_99_9_percent"],
                },
            },
        }
        return (1 if self.audit_fail else 0), {"status": "passed", "models": [audit]}


@pytest.fixture
def setup_runner(tmp_path):
    templates, variants = m.load_templates(tmp_path)
    runtime = FakeRuntime(variants)
    baseline = {"jobs": [], "pending_ipos": []}
    return m.Runner(tmp_path, runtime, templates, variants, baseline), runtime


def test_failure_latches_and_manual_resume_keeps_failed_attempt(setup_runner):
    runner, rt = setup_runner
    rt.fail[("raw", "2024-01-30", "v1")] = 2
    rt.high_after = True
    assert runner.run(m.START) == 1
    assert runner.ledger["status"] == "needs_attention"
    assert runner.ledger["last_stop"]["reason"] == "raw_failed_unclassified"
    before = list(rt.calls)
    assert runner.run(m.START) == 1
    assert rt.calls == before
    rt.fail.clear()
    rt.high_after = False
    assert runner.run(m.START, resume_after_review="Reviewed simulated raw failure") == 0
    assert len(runner.ledger["attempts"]) == 4
    assert runner.ledger["attempts"][0]["status"] == "failed"
    before = list(rt.calls)
    assert runner.run(m.START) == 0
    assert rt.calls == before


def test_typed_budget_only_resumes_next_local_day(setup_runner, monkeypatch):
    runner, rt = setup_runner
    monkeypatch.setattr(m, "local_day", lambda: "2026-10-23")
    rt.fail[("raw", "2024-01-30", "v1")] = 2
    rt.typed_budget = True
    assert runner.run(m.START) == 2
    before = list(rt.calls)
    assert runner.run(m.START) == 2
    assert rt.calls == before
    monkeypatch.setattr(m, "local_day", lambda: "2026-10-24")
    rt.fail.clear()
    rt.typed_budget = False
    assert runner.run(m.START) == 0
    assert runner.ledger["attempts"][0]["status"] == "quota_deferred"


def test_ipo_exit4_and_cross_month_recovery(setup_runner):
    runner, rt = setup_runner
    rt.gaps = {("2024-01-31", model) for model in m.MODELS}
    assert runner.run(date(2024, 1, 31)) == 0
    assert len(runner.ledger["pending_ipos"]) == 3
    assert all(p["expected_next_day"] == "2024-02-01" for p in runner.ledger["pending_ipos"])
    report = json.loads((runner.base / "reports/2024-01.json").read_text())
    assert report["ipo_origin_count"] == 3
    assert not report["validation_complete"]
    assert len(report["below_99_9_model_days"]) == 3
    restored = m.Runner(runner.base, rt, runner.templates, runner.variants, runner.baseline)
    assert restored.run(date(2024, 2, 1)) == 0
    assert all(p["status"] == "confirmed" for p in restored.ledger["pending_ipos"])
    assert json.loads((runner.base / "reports/2024-01.json").read_text())["validation_complete"]


def test_ipo_not_recovered_stops_before_ingest(setup_runner):
    runner, rt = setup_runner
    rt.gaps = {("2024-01-31", "v1"), ("2024-02-01", "v1")}
    assert runner.run(date(2024, 1, 31)) == 0
    assert runner.run(date(2024, 2, 1)) == 1
    assert runner.ledger["last_stop"]["reason"] == "ipo_not_recovered_next_trading_day"
    assert ("ingest", "2024-02-01", "v1") not in rt.calls


@pytest.mark.parametrize("failure", ["audit", "exit4", "unknown_gap"])
def test_only_audited_ipo_exit4_continues(setup_runner, failure):
    runner, rt = setup_runner
    rt.audit_fail = failure == "audit"
    rt.force_exit4 = failure == "exit4"
    if failure == "unknown_gap":
        rt.gaps.add(("2024-01-30", "v1"))
        rt.bad_gap = True
    assert runner.run(m.START) == 1
    assert runner.ledger["status"] == "needs_attention"
    assert not any(call[2] == "v2" for call in rt.calls)


def test_version_change_stops_before_next_mutation(setup_runner):
    runner, rt = setup_runner
    rt.changed_after_raw = True
    assert runner.run(m.START) == 1
    assert rt.calls == [("raw", "2024-01-30", "v1")]
    assert runner.ledger["last_stop"]["reason"] == "importer_version_changed"


def test_interrupted_attempt_requires_review(setup_runner):
    runner, rt = setup_runner
    runner.ledger["attempts"].append({"day": "2024-01-30", "model": "v1", "status": "running"})
    assert runner.run(m.START) == 1
    assert runner.ledger["attempts"][0]["status"] == "interrupted"
    assert not rt.calls


def test_terminal_ipo_stays_pending_without_extended_range(setup_runner):
    runner, rt = setup_runner
    rt.gaps = {(str(m.END), model) for model in m.MODELS}
    assert runner.run(m.END) == 1
    assert runner.ledger["last_stop"]["reason"] == "terminal_ipo_recovery_unconfirmed"
    assert all(p["expected_next_day"] is None for p in runner.ledger["pending_ipos"])
    assert max(call[1] for call in rt.calls) == str(m.END)


def test_range_is_bounded():
    assert m.month_limit("2026-10") == m.END
    assert m.month_limit(None) == m.END
    for month in ("2026-11", "2023-12", "2026-13", "wrong"):
        with pytest.raises(m.StopRunError):
            m.month_limit(month)


def test_quota_report_groups_real_observation_dates_and_marks_reset(setup_runner):
    runner, _ = setup_runner
    runner.ledger["jobs"]["2024-01-30/v1"] = {
        "day": "2024-01-30",
        "model": "v1",
        "status": "pending",
    }
    for i, (day, used) in enumerate([("23", 100), ("23", 150), ("24", 10), ("24", 30), ("24", 5)]):
        runner.ledger["attempts"].append(
            {
                "day": "2024-01-30",
                "model": "v1",
                "status": "failed",
                "quota_before": {
                    "observed_at": f"2026-10-{day}T01:0{i}:00+00:00",
                    "bytes_used": used,
                },
            }
        )
    runner.reports()
    quota = json.loads((runner.base / "reports/2024-01.json").read_text())["quota"]
    assert quota["observed_nonnegative_delta_sum_bytes"] == 50
    assert quota["by_observation_day"][0]["observation_day"] == "2026-10-23"
    assert quota["by_observation_day"][1]["reset_or_unknown"]
    assert quota["by_observation_day"][1]["observed_delta_bytes"] is None


def test_baseline_missing_optional_review_field_keeps_ipo(tmp_path, monkeypatch):
    seed = tmp_path / "seed"
    seed.mkdir()
    monkeypatch.setattr(m, "SEED", seed)
    entry = {"day": "2024-01-03", "model": "v1", "audit_exit": 0, "raw_exit": 0, "ingest_exit": 0}
    m.atomic_json(
        seed / "batches.json", {"importer_version": m.IMPORTER_VERSION, "batches": [entry]}
    )
    gap = {
        "instrument_id": 717,
        "status": "partial_bundle",
        "pieces": {"exposure": True, "specific_risk": True, "specific_return": False},
    }
    m.atomic_json(
        seed / "2024-01-03/v1-audit.json",
        {"models": [{"status": "passed", "not_included_candidates": [gap], "import_evidence": {}}]},
    )
    baseline = m.import_baseline(tmp_path / "new")
    assert baseline["jobs"][0]["known_ipo_ids"] == [717]


def test_subprocesses_inherit_runner_lock(tmp_path, monkeypatch):
    seen = []

    def fake_run(*args, **kwargs):
        seen.append(kwargs["pass_fds"])
        return SimpleNamespace(returncode=0, stdout=m.IMPORTER_VERSION.encode())

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    rt = m.Runtime(tmp_path, lock_fd=88)
    monkeypatch.setattr(rt, "prepare_account", lambda: SimpleNamespace(values={}))
    assert rt.check_version() == m.IMPORTER_VERSION
    rt.command("raw", tmp_path / "v1.yaml", "2024-01", tmp_path / "raw.log")
    rt.audit("v1", tmp_path, tmp_path / "audit.json", tmp_path / "audit.log")
    assert seen == [(88,), (88,), (88,)]


def test_alias_identity_is_shared_across_dates_and_models(setup_runner):
    runner, _ = setup_runner

    def manifest(code, iid):
        return {"coverage": [{"request_code": code, "instrument_id": iid, "status": "included"}]}

    prior = runner.special_check("2025-02-14", "v1", manifest("300114.XSHE", 10))
    runner.ledger["jobs"]["2025-02-14/v1"] = {"special_checks": prior}
    with pytest.raises(m.StopRunError, match="models_disagree"):
        runner.special_check("2025-02-14", "v2", manifest("300114.XSHE", 11))
    with pytest.raises(m.StopRunError, match="identity_changed"):
        runner.special_check("2025-02-17", "v1", manifest("302132.XSHE", 11))
    assert runner.special_check("2025-02-17", "v1", manifest("302132.XSHE", 10))["alias_covered"]


def test_explicit_new_account_can_resume_but_old_account_stays_locked(setup_runner, monkeypatch):
    runner, rt = setup_runner
    monkeypatch.setattr(m, "local_day", lambda: "2026-10-23")
    rt.fail[("raw", "2024-01-30", "v1")] = 2
    rt.typed_budget = True
    assert runner.run(m.START) == 2
    rt.account_env = "RICEQUANT_API_KEY_SECOND"
    second = m.Runner(runner.base, rt, runner.templates, runner.variants, runner.baseline)
    assert second.run(m.START) == 2
    assert len(second.ledger["attempts"]) == 2
    assert second.ledger["attempts"][-1]["account_env"] == rt.account_env
    assert second.ledger["attempts"][-1]["quota_before"]["account_env"] == rt.account_env
    rt.account_env = m.ACCOUNT_ENV
    original = m.Runner(runner.base, rt, runner.templates, runner.variants, runner.baseline)
    before = list(rt.calls)
    assert original.run(m.START) == 2
    assert rt.calls == before
    assert original.ledger["variants"] == runner.variants


def test_new_account_cannot_bypass_quality_latch(setup_runner):
    runner, rt = setup_runner
    rt.fail[("raw", "2024-01-30", "v1")] = 2
    assert runner.run(m.START) == 1
    rt.account_env = "RICEQUANT_API_KEY_SECOND"
    rt.fail.clear()
    second = m.Runner(runner.base, rt, runner.templates, runner.variants, runner.baseline)
    before = list(rt.calls)
    assert second.run(m.START) == 1
    assert rt.calls == before
    assert second.ledger["status"] == "needs_attention"


def test_selected_account_missing_is_sanitized(tmp_path, monkeypatch):
    from gr_tools.config import Environment

    monkeypatch.setattr(
        "gr_tools.config.load_environment",
        lambda **_: Environment(tmp_path, {m.ACCOUNT_ENV: "fake-sensitive-key"}),
    )
    rt = m.Runtime(tmp_path, account_env="RICEQUANT_API_KEY_SECOND")
    with pytest.raises(m.StopRunError) as exc:
        rt.prepare_account()
    assert str(exc.value) == "selected_account_key_missing"
    assert "fake-sensitive-key" not in str(exc.value)
    assert not list(tmp_path.iterdir())


def test_selected_key_snapshot_is_shared_by_quota_and_raw_only(tmp_path, monkeypatch):
    from gr_tools.config import Environment

    original_env = dict(m.os.environ)
    snapshot = Environment(tmp_path, {m.ACCOUNT_ENV: "fake-original", "ALT_KEY": "fake-selected"})
    monkeypatch.setattr("gr_tools.config.load_environment", lambda **_: snapshot)
    seen = []

    def fake_run(*args, **kwargs):
        seen.append(kwargs.get("env"))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    rt = m.Runtime(tmp_path, account_env="ALT_KEY")
    selected = rt.prepare_account()
    assert selected.values[m.ACCOUNT_ENV] == "fake-selected"
    assert dict(m.os.environ) == original_env
    # 后续源快照变化也不能使同次执行悄然切换账号。
    monkeypatch.setattr("gr_tools.config.load_environment", lambda **_: Environment(tmp_path, {}))
    assert rt.prepare_account() is selected
    rt.command("raw", tmp_path / "v1.yaml", "2024-01", tmp_path / "raw.log")
    rt.command("ingest", tmp_path / "v1.yaml", "2024-01", tmp_path / "ingest.log")
    assert seen[0][m.ACCOUNT_ENV] == "fake-selected"
    assert seen[1] is None
    assert all("fake-selected" not in file.read_text() for file in tmp_path.iterdir())


def test_quota_deltas_never_subtract_across_accounts(setup_runner):
    runner, _ = setup_runner
    runner.ledger["jobs"]["2024-01-30/v1"] = {
        "day": "2024-01-30",
        "model": "v1",
        "status": "pending",
    }
    for account, used in [
        (m.ACCOUNT_ENV, 800),
        (m.ACCOUNT_ENV, 850),
        ("ALT_KEY", 10),
        ("ALT_KEY", 30),
    ]:
        runner.ledger["attempts"].append(
            {
                "day": "2024-01-30",
                "model": "v1",
                "status": "failed",
                "account_env": account,
                "quota_before": {"observed_at": "2026-10-23T01:00:00+00:00", "bytes_used": used},
            }
        )
    runner.reports()
    quota = json.loads((runner.base / "reports/2024-01.json").read_text())["quota"]
    assert quota["observed_nonnegative_delta_sum_bytes"] == 70
    assert {
        row["account_env"]: row["observed_delta_bytes"] for row in quota["by_observation_day"]
    } == {m.ACCOUNT_ENV: 50, "ALT_KEY": 20}


def test_legacy_budget_stop_applies_to_original_account_only(setup_runner, monkeypatch):
    runner, rt = setup_runner
    monkeypatch.setattr(m, "local_day", lambda: "2026-10-23")
    runner.ledger.update(status="budget_deferred", quota_stop={"local_day": "2026-10-23"})
    runner.save()
    rt.account_env = "ALT_KEY"
    resumed = m.Runner(runner.base, rt, runner.templates, runner.variants, runner.baseline)
    assert resumed.run(m.START) == 0
    assert resumed.ledger["quota_stops"][m.ACCOUNT_ENV]["local_day"] == "2026-10-23"
    assert resumed.ledger["account_env"] == m.ACCOUNT_ENV


def test_quota_client_uses_same_selected_snapshot_as_raw(tmp_path, monkeypatch):
    from gr_tools.config import Environment

    snapshot = Environment(tmp_path, {m.ACCOUNT_ENV: "fake-old", "ALT_KEY": "fake-new"})
    monkeypatch.setattr("gr_tools.config.load_environment", lambda **_: snapshot)
    captured = {}

    def fake_config(path, *, environment):
        captured["environment"] = environment
        return object()

    def fake_client(provider, config):
        captured["provider"] = provider
        return object()

    monkeypatch.setattr("gr_data.config.pipeline.load_config", fake_config)
    monkeypatch.setattr("gr_data.raw._build_client", fake_client)
    monkeypatch.setattr(
        "gr_data.raw.ricequant.riskmodel._quota_snapshot",
        lambda _: {
            "bytes_used": 10,
            "bytes_limit": 1000,
            "observed_at": "2026-10-23T00:00:00+00:00",
        },
    )
    rt = m.Runtime(tmp_path, account_env="ALT_KEY")
    observation = rt.quota()
    assert captured["environment"] is rt.prepare_account()
    assert captured["environment"].values[m.ACCOUNT_ENV] == "fake-new"
    assert observation["account_env"] == "ALT_KEY"
    assert "fake-new" not in json.dumps(observation)
