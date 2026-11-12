"""阶段A失败后重新采集；不连接PG或真实供应商。"""

from __future__ import annotations

import json
from argparse import Namespace
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import polars as pl
import pytest
from gr_data.config.ricequant_risk import RiskOptions
from gr_data.diagnosis_daily import cli
from gr_data.diagnosis_daily.evidence import write_json
from gr_data.diagnostic_publication import ENHANCED_BASIC_DATASETS


@pytest.mark.parametrize("action,residue", [("prepare", "manifest"), ("run", "round")])
def test_phase_a_retry_archives_failed_attempt_and_fetches_fresh_data(
    monkeypatch, tmp_path, action, residue
):
    import gr_data.diagnosis_daily as daily

    day = date(2024, 1, 3)
    artifact = tmp_path / "diagnosis/daily" / str(day)
    calls = []

    class Connection:
        @contextmanager
        def transaction(self):
            yield

        def execute(self, query, args=None):
            assert query.startswith(("SET ", "SELECT "))
            calls.append(query)
            rows = []
            if "SELECT target,provider" in query:
                rows = [(table, "tushare") for table in ENHANCED_BASIC_DATASETS]
            elif "SELECT DISTINCT instrument_id" in query:
                rows = [(1,)]
            elif "SELECT trading_day FROM" in query:
                rows = [(day,)]
            return SimpleNamespace(fetchone=lambda: (1,), fetchall=lambda: rows)

    @contextmanager
    def connection(pg):
        yield Connection()

    previous = {"as_of_date": day - timedelta(days=1), "data_version_id": "previous", "valid": True}
    options = RiskOptions("v2", "sws_2021", day, day, (), {}, "verified source units")
    monkeypatch.setattr(daily, "connect", connection)
    monkeypatch.setattr(cli, "connect", connection)
    monkeypatch.setattr(daily, "latest_publication", lambda c: previous)
    monkeypatch.setattr(cli, "latest_publication", lambda c: previous)
    monkeypatch.setattr(daily, "get_importer_version", lambda **kwargs: "code")
    monkeypatch.setattr(daily, "risk_options", lambda *args: options)
    monkeypatch.setattr(daily, "fingerprints", lambda *args: {"accepted": "baseline"})
    frames = {
        "classify.instrument_industry": pl.DataFrame({"instrument_id": [1]}),
        "fundamental.indicator_q": pl.DataFrame({"instrument_id": [1]}),
    }
    monkeypatch.setattr(
        daily,
        "normalize_tushare",
        lambda *args: (frames, {"instruments": [{"instrument_id": 1}]}, {"600000.SH": 1}, day),
    )
    ts, rq = Mock(), Mock()
    monkeypatch.setattr("gr_data.raw.tushare.client.TushareProClient", lambda *args: ts)
    monkeypatch.setattr("gr_data.raw.ricequant.client.RqdatacClient", lambda **kwargs: rq)
    monkeypatch.setattr("gr_data.cli._pg", lambda cfg: Mock())

    def capture_tushare(client, paths, *args):
        assert not paths.root.exists(), "Fresh capture must start without previous raw files"
        client.fetch()
        write_json(paths.dataset_dir("tushare", "daily") / "response.json", {"fresh": True})
        return datetime.now(timezone.utc)

    def capture_risk(client, paths, *args):
        root = paths.dataset_dir("ricequant", "rq_risk_model")
        # 模拟init复用旧观察/旧证券计划：没有归档时第二次不会调用供应商。
        if list(root.rglob("manifest.json")) or (root / "round-stale.json").exists():
            raise ValueError("Cached incomplete risk observation or stale universe")
        client.fetch()
        if client.fetch.call_count == 1:
            if residue == "manifest":
                write_json(
                    root / str(day) / "old-observation/manifest.json",
                    {
                        "included": 1,
                        "candidate": 2000,
                    },
                )
            else:
                write_json(root / "round-stale.json", {"universes": {str(day): "old universe"}})
                write_json(root / "_failed" / str(day) / "response.json", {"partial": True})
            write_json(artifact / "canonical/partial.json", {"incomplete": True})
            raise ValueError(
                "Insufficient risk coverage" if residue == "manifest" else "Interrupted capture"
            )
        write_json(
            root / str(day) / "new-observation/manifest.json",
            {
                "included": 2000,
                "candidate": 2000,
            },
        )
        return {
            "security_ids": [1],
            "quality": {"publication_eligible": True},
            "manifest": {"observation_id": "new-observation"},
        }

    monkeypatch.setattr(daily, "collect_tushare", capture_tushare)
    monkeypatch.setattr(daily, "collect_risk", capture_risk)

    def accepted_stage_b(pg, path):
        prepared = json.loads((path / "prepared.json").read_text())
        return {
            "version_id": prepared["version_id"],
            "archived_attempt": prepared["archived_attempt"],
        }

    stage_b = Mock(side_effect=accepted_stage_b)
    monkeypatch.setattr(cli, "apply", stage_b)
    args = Namespace(
        action=action,
        artifact=None,
        day=day if action == "prepare" else None,
        start=day,
        end=day,
        reuse_raw=None,
    )
    cfg = Mock(raw_root=tmp_path, environment=SimpleNamespace(values={}))
    assert cli.run(args, cfg) == 1
    assert not (artifact / "prepared.json").exists()
    failed = {p.relative_to(artifact): p.read_bytes() for p in artifact.rglob("*") if p.is_file()}
    stage_b.assert_not_called()

    assert cli.run(args, cfg) == 0
    prepared = json.loads((artifact / "prepared.json").read_text())
    archived = Path(prepared["archived_attempt"]["path"])
    assert archived.parent == artifact.parent / "_failed"
    assert archived.name.startswith(str(day) + "-")
    assert {
        p.relative_to(archived): p.read_bytes() for p in archived.rglob("*") if p.is_file()
    } == failed
    assert ts.fetch.call_count == rq.fetch.call_count == 2
    assert all(
        "old-observation" not in p and "round-stale" not in p and "_failed" not in p
        for p in prepared["raw_files"]
    )
    assert not (artifact / "canonical/partial.json").exists()
    status = json.loads((artifact / "status.json").read_text())
    assert status["archived_attempt"] == prepared["archived_attempt"]
    last = json.loads((artifact.parent / "last-run.json").read_text())
    result = last["result"] if action == "prepare" else last["result"]["publications"][0]
    assert result["archived_attempt"] == prepared["archived_attempt"]

    # 完整产物不能被重抓或归档，状态文件同样保持不变。
    before = {p.relative_to(artifact): p.read_bytes() for p in artifact.rglob("*") if p.is_file()}
    reads = len(calls)
    with pytest.raises(ValueError, match="immutable"):
        daily.prepare(Mock(), artifact, day, tushare=ts, ricequant=rq)
    assert {
        p.relative_to(artifact): p.read_bytes() for p in artifact.rglob("*") if p.is_file()
    } == before
    assert len(calls) == reads and rq.fetch.call_count == 2
