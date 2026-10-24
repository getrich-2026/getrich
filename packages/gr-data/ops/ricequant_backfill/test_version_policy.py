from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    "version_runner", Path(__file__).with_name("run_monthly_accounts.py")
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def sample(tmp_path):
    job = {
        "status": "complete",
        "observation_id": "old",
        "run_id": "oldrun",
        "import_evidence": {"importer_version": m.IMPORTER_VERSION},
    }
    ledger = {
        "jobs": {"2024-12-10/v1": job},
        "attempts": [
            {
                "status": "failed",
                "day": "2024-12-11",
                "model": "v2",
                "audit_exit": 1,
                "observation_id": "608016044ef54173a077abe5445c03b5",
            }
        ],
    }
    policy = {
        "schema_version": 1,
        "legacy_importer_version": m.IMPORTER_VERSION,
        "current_importer_version": "b" * 40,
        "legacy_jobs": {"2024-12-10/v1": m.evidence_digest(job)},
        "legacy_attempt_count": 1,
        "legacy_attempts_sha256": m.evidence_digest(ledger["attempts"]),
        "repair": {
            "key": "2024-12-11/v2",
            "old_observation_id": "608016044ef54173a077abe5445c03b5",
            "old_run_id": "4cc48d3d-663a-5fc9-be51-17548ec23966",
            "observation_id": "c" * 32,
        },
    }
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy))
    return path, ledger


def test_policy_preserves_failed_attempts(tmp_path):
    path, ledger = sample(tmp_path)
    before = json.dumps(ledger)
    assert m.load_version_policy(path, ledger)["current_importer_version"] == "b" * 40
    assert json.dumps(ledger) == before


def test_old_job_version_mutation_rejected(tmp_path):
    path, ledger = sample(tmp_path)
    ledger["jobs"]["2024-12-10/v1"]["import_evidence"]["importer_version"] = "b" * 40
    with pytest.raises(m.StopRunError, match="legacy_job_evidence_changed"):
        m.load_version_policy(path, ledger)


def test_unknown_new_job_version_rejected(tmp_path):
    path, ledger = sample(tmp_path)
    ledger["jobs"]["2024-12-12/v1"] = {"status": "complete", "importer_version": "d" * 40}
    with pytest.raises(m.StopRunError, match="unknown_job_version"):
        m.load_version_policy(path, ledger)


def test_old_failed_attempt_modification_rejected(tmp_path):
    path, ledger = sample(tmp_path)
    ledger["attempts"][0]["status"] = "passed"
    with pytest.raises(m.StopRunError, match="legacy_attempt_evidence_changed"):
        m.load_version_policy(path, ledger)


def test_double_observation_requires_selection():
    bundles = [({"observation_id": "old"}, {}), ({"observation_id": "new"}, {"exposure": "new"})]
    with pytest.raises(m.StopRunError, match="explicit_observation"):
        m.select_bundle(bundles, None)
    assert m.select_bundle(bundles, "new")[1] == {"exposure": "new"}
    with pytest.raises(m.StopRunError, match="explicit_observation"):
        m.select_bundle(bundles, "missing")


def test_old_observation_cannot_be_repair_target(tmp_path):
    path, ledger = sample(tmp_path)
    policy = json.loads(path.read_text())
    policy["repair"]["observation_id"] = policy["repair"]["old_observation_id"]
    path.write_text(json.dumps(policy))
    with pytest.raises(m.StopRunError, match="invalid_repair"):
        m.load_version_policy(path, ledger)


@pytest.mark.parametrize("audit_failed", [False, True])
def test_selected_repair_audits_new_version_and_retains_failure(tmp_path, audit_failed):
    fake_spec = importlib.util.spec_from_file_location(
        "fake_runner", Path(__file__).with_name("test_run_monthly_accounts.py")
    )
    fake = importlib.util.module_from_spec(fake_spec)
    fake_spec.loader.exec_module(fake)
    templates, variants = m.load_templates(tmp_path)

    class Runtime(fake.FakeRuntime):
        def check_version(self):
            return "b" * 40

        def bundle(self, config, *, observation_id=None):
            manifest, frames = super().bundle(config)
            manifest["observation_id"] = "c" * 32
            if observation_id is not None:
                assert observation_id == "c" * 32
            return manifest, frames

        def command(self, phase, config, month, log, *, observation_id=None):
            if phase == "ingest":
                assert observation_id == "c" * 32
            return super().command(phase, config, month, log)

        def audit(self, model, directory, output, log, *, observation_id, importer_version):
            assert observation_id == "c" * 32 and importer_version == "b" * 40
            code, report = super().audit(model, directory, output, log)
            report["models"][0]["import_evidence"]["importer_version"] = "b" * 40
            return code, report

    path, old = sample(tmp_path)
    policy = json.loads(path.read_text())
    baseline = {"jobs": [], "pending_ipos": []}
    policy["baseline_sha256"] = m.evidence_digest(baseline)
    runner = m.Runner(tmp_path, Runtime(variants), templates, variants, baseline, policy=policy)
    runner.ledger["attempts"] = old["attempts"][:]
    original = json.loads(json.dumps(runner.ledger["attempts"][0]))
    runner.ledger["calendar"] = ["2024-12-11", "2024-12-12"]
    runner.runtime.audit_fail = audit_failed
    if audit_failed:
        runner.ledger["jobs"]["2024-12-11/v2"] = {
            "day": "2024-12-11",
            "model": "v2",
            "status": "pending",
        }
        old_job = dict(runner.ledger["jobs"]["2024-12-11/v2"])
        with pytest.raises(m.StopRunError, match="independent_audit_failed"):
            runner.run_job("2024-12-11", "v2")
        assert runner.ledger["jobs"]["2024-12-11/v2"] == old_job
        assert runner.ledger.get("supersessions", []) == []
        assert runner.ledger["attempts"][0] == original
        return
    runner.run_job("2024-12-11", "v2")
    assert runner.ledger["attempts"][0] == original
    assert runner.ledger["jobs"]["2024-12-11/v2"]["importer_version"] == "b" * 40
    assert runner.ledger["supersessions"][0]["old_run_id"] == policy["repair"]["old_run_id"]
    assert runner.ledger["supersessions"][0]["new_run_id"] == "run"


def test_policy_change_after_pin_rejected(tmp_path):
    path, ledger = sample(tmp_path)
    policy = json.loads(path.read_text())
    ledger["version_policy_sha256"] = m.evidence_digest(policy)
    policy["current_importer_version"] = "e" * 40
    path.write_text(json.dumps(policy))
    with pytest.raises(m.StopRunError, match="version_policy_changed"):
        m.load_version_policy(path, ledger)


def test_runtime_passes_selection_to_raw_reader(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import gr_data.config.pipeline as pipeline
    import gr_data.config.ricequant_risk as risk_config
    import gr_data.raw.ricequant.riskmodel as raw

    cfg = SimpleNamespace(raw_root=tmp_path, section=lambda *args: {})
    monkeypatch.setattr(pipeline, "load_config", lambda config: cfg)
    monkeypatch.setattr(risk_config, "parse_risk_options", lambda options: object())
    seen = []

    def read(paths, options, *, observation_id=None):
        seen.append(observation_id)
        assert observation_id == "selected"
        yield {"observation_id": "selected"}, {}

    monkeypatch.setattr(raw, "read_bundles", read)
    assert (
        m.Runtime(tmp_path).bundle(tmp_path / "config.yaml", observation_id="selected")[0][
            "observation_id"
        ]
        == "selected"
    )
    assert seen == ["selected"]


def test_audit_reader_selection_is_pushed_down():
    # 审计 CLI 的只读 DB 流程另有覆盖；这里静态约束调用边界，防止退回加载全量后过滤。
    import ast

    tree = ast.parse(Path(__file__).with_name("audit_monthly.py").read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "read_bundles"
    ]
    assert len(calls) == 1
    selection = next(
        keyword.value for keyword in calls[0].keywords if keyword.arg == "observation_id"
    )
    assert isinstance(selection, ast.Attribute) and selection.attr == "observation_id"
