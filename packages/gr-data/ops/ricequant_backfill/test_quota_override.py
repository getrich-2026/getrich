from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from gr_data.common.ricequant_specs import BudgetDeferredError
from gr_data.config.ricequant_risk import parse_risk_options
from gr_data.raw.ricequant.fetchers.supplements import _check_quota


spec = importlib.util.spec_from_file_location(
    "quota_runner", Path(__file__).with_name("run_monthly_accounts.py")
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.fixture(autouse=True)
def authorization_clock(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 25, 12, tzinfo=tz)

    monkeypatch.setattr(m, "datetime", Clock)


def test_default_keeps_ten_percent_reserve(tmp_path):
    rt = m.Runtime(tmp_path)
    assert rt.quota_reserve_fraction() == 0.1
    assert m.quota_exhausted({"bytes_used": 900, "bytes_limit": 1000})


def test_zero_reserve_still_stops_at_exhaustion(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "local_day", lambda: "2026-10-25")
    rt = m.Runtime(tmp_path, use_full_quota_on="2026-10-25")
    reserve = rt.quota_reserve_fraction()
    assert reserve == 0
    assert not m.quota_exhausted({"bytes_used": 999, "bytes_limit": 1000}, reserve)
    assert m.quota_exhausted({"bytes_used": 1000, "bytes_limit": 1000}, reserve)
    client = SimpleNamespace(get_quota=lambda: {"bytes_used": 1000, "bytes_limit": 1000})
    with pytest.raises(BudgetDeferredError):
        _check_quota(client, reserve)


def test_expired_authorization_rejects_new_process(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "local_day", lambda: "2026-10-26")
    with pytest.raises(m.StopRunError, match="quota_override_expired") as error:
        m.Runtime(tmp_path, use_full_quota_on="2026-10-25")
    assert error.value.quota


def test_day_rollover_rejects_next_job(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "local_day", lambda: "2026-10-25")
    rt = m.Runtime(tmp_path, use_full_quota_on="2026-10-25")
    monkeypatch.setattr(m, "local_day", lambda: "2026-10-26")
    with pytest.raises(m.StopRunError, match="quota_override_expired"):
        rt.quota_reserve_fraction()


@pytest.mark.parametrize("reserve", [-1, 1, float("nan"), float("inf"), True])
def test_invalid_reserve_cannot_disable_budget_checks(reserve):
    with pytest.raises(m.StopRunError, match="invalid_quota_reserve"):
        m.quota_exhausted({"bytes_used": 1, "bytes_limit": 1000}, reserve)


def test_raw_override_preserves_variant_and_original_config(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "local_day", lambda: "2026-10-25")
    template = m.SEED / "v1.yaml"
    config = tmp_path / "v1.yaml"
    original = template.read_text()
    config.write_text(original)
    data = yaml.safe_load(original)
    identity = parse_risk_options(data["providers"]["ricequant"]["risk_model"]).variant_id
    rt = m.Runtime(tmp_path, lock_fd=88, use_full_quota_on="2026-10-25")
    monkeypatch.setattr(rt, "prepare_account", lambda: SimpleNamespace(values={}))
    seen = []

    def fake_run(args, **kwargs):
        selected = Path(args[args.index("--config") + 1])
        seen.append((selected, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    assert rt.command("raw", config, "2026-08", tmp_path / "raw.log") == 0
    raw_config = yaml.safe_load(seen[0][0].read_text())
    assert raw_config["providers"]["ricequant"]["supplements"] == {"quota_reserve_fraction": 0}
    assert (
        parse_risk_options(raw_config["providers"]["ricequant"]["risk_model"]).variant_id
        == identity
    )
    assert config.read_text() == original
    assert seen[0][1]["pass_fds"] == (88,)
    assert 0 < seen[0][1]["timeout"] <= 1800
    assert rt.command("ingest", config, "2026-08", tmp_path / "ingest.log") == 0
    assert seen[1][0] == config


@pytest.mark.parametrize("crossing", ["config_write", "account_prepare"])
def test_midnight_crossing_cannot_start_zero_reserve_child(tmp_path, monkeypatch, crossing):
    current_day = ["2026-10-25"]
    monkeypatch.setattr(m, "local_day", lambda: current_day[0])
    rt = m.Runtime(tmp_path, use_full_quota_on="2026-10-25")
    config = tmp_path / "v1.yaml"
    config.write_text((m.SEED / "v1.yaml").read_text())
    original_write = m.atomic_text

    def write(path, content):
        original_write(path, content)
        if crossing == "config_write":
            current_day[0] = "2026-10-26"

    def prepare():
        if crossing == "account_prepare":
            current_day[0] = "2026-10-26"
        return SimpleNamespace(values={})

    monkeypatch.setattr(m, "atomic_text", write)
    monkeypatch.setattr(rt, "prepare_account", prepare)
    monkeypatch.setattr(
        m.subprocess, "run", lambda *a, **k: pytest.fail("child started after expiry")
    )
    with pytest.raises(m.StopRunError, match="quota_override_expired"):
        rt.command("raw", config, "2026-08", tmp_path / "raw.log")
