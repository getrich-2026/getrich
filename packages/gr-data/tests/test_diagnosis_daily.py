"""两阶段日更边界回归；真实事务场景另由显式隔离PG用例覆盖。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import polars as pl
import pytest
from gr_data.cli import build_parser
from gr_data.diagnosis_daily import _load, apply, prepare
from gr_data.diagnosis_daily.evidence import digest, file_hash, write_json
from gr_data.ingest.base import IngestContext
from gr_data.ingest.ricequant.riskmodel import run_risk_ingest
from psycopg.pq import TransactionStatus


def test_daily_cli_has_finite_phase_actions():
    parser = build_parser()
    args = parser.parse_args(
        ["diagnosis-daily", "run", "--start", "2026-11-06", "--end", "2026-11-12"]
    )
    assert args.start == date(2026, 11, 6) and args.end == date(2026, 11, 12)
    assert parser.parse_args(
        ["diagnosis-daily", "apply", "--artifact", "/tmp/day"]
    ).artifact == Path("/tmp/day")


def test_phase_a_configuration_failure_never_opens_writer(monkeypatch, tmp_path):
    import gr_data.diagnosis_daily as daily

    def reject(**kwargs):
        raise ValueError("uncommitted source")

    monkeypatch.setattr(daily, "get_importer_version", reject)
    connection = Mock()
    monkeypatch.setattr(daily, "connect", connection)
    with pytest.raises(ValueError, match="uncommitted"):
        prepare(Mock(), tmp_path, date(2026, 11, 6), tushare=Mock(), ricequant=Mock())
    connection.assert_not_called()
    assert json.loads((tmp_path / "status.json").read_text())["phase"] == "A"
    assert not (tmp_path / "prepared.json").exists()


def test_artifact_tampering_is_rejected_before_writer_connection(monkeypatch, tmp_path):
    import gr_data.diagnosis_daily as daily

    monkeypatch.setattr(daily, "get_importer_version", lambda **kwargs: "code")
    raw = tmp_path / "raw"
    raw.mkdir()
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    file = canonical / "meta.symbol_map.parquet"
    pl.DataFrame({"instrument_id": [1]}).write_parquet(file)
    data = {
        "importer_version": "code",
        "raw_root": str(raw),
        "canonical_files": {"canonical/meta.symbol_map.parquet": file_hash(file)},
        "raw_files": {},
    }
    data["artifact_hash"] = digest(data)
    data["version_id"] = "daily-test"
    write_json(tmp_path / "prepared.json", data)
    pl.DataFrame({"instrument_id": [2]}).write_parquet(file)
    writer = Mock()
    monkeypatch.setattr(daily, "connect", writer)
    with pytest.raises(ValueError, match="checksum"):
        apply(Mock(), tmp_path)
    writer.assert_not_called()
    data["day"] = "2026-11-07"
    write_json(tmp_path / "prepared.json", data)
    with pytest.raises(ValueError, match="identity changed"):
        _load(tmp_path)


def test_managed_risk_import_requires_outer_transaction(monkeypatch, tmp_path):
    from gr_data.common.paths import RawPaths
    from gr_data.config.ricequant_risk import RiskOptions

    options = RiskOptions(
        "v2",
        "sws_2021",
        date(2026, 11, 6),
        date(2026, 11, 6),
        (),
        {},
        "evidence",
        universe_policy="listed_cn_a_v2",
        purpose="production",
    )
    conn = Mock()
    conn.info.transaction_status = TransactionStatus.IDLE
    with pytest.raises(ValueError, match="transaction boundary"):
        run_risk_ingest(conn, IngestContext(RawPaths(tmp_path)), options, transaction_managed=True)
    conn.commit.assert_not_called()
    conn.rollback.assert_not_called()
