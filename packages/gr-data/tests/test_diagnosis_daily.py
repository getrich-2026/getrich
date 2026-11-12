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


def test_expired_verified_alias_is_not_a_production_history_override():
    from gr_data.diagnosis_daily.collect import current_alias_snapshot

    metadata = {
        "instruments": [{"instrument_id": 1, "symbol": "601607.SH"}],
        "aliases": [
            {"instrument_id": 1, "source": "tushare", "source_symbol": "600849.SH"},
            {"instrument_id": 1, "source": "tushare", "source_symbol": "601607.SH"},
            {"instrument_id": 1, "source": "tushare", "source_symbol": "unknown.SH"},
        ],
    }
    snapshot, evidence = current_alias_snapshot(metadata, date(2026, 11, 6))
    assert [r["source_symbol"] for r in snapshot["aliases"]] == ["601607.SH", "unknown.SH"]
    assert evidence["expired_aliases"][0]["source_symbol"] == "600849.SH"
    assert len(metadata["aliases"]) == 3
    old, _ = current_alias_snapshot(metadata, date(2010, 3, 4))
    assert len(old["aliases"]) == 3


@pytest.mark.parametrize("status", ["included", "partial_bundle"])
def test_phase_a_checks_every_risk_identity_including_exclusions(status):
    from gr_data.diagnosis_daily.collect import validate_risk_identities

    metadata = {
        "instruments": [
            {
                "instrument_id": 42,
                "symbol": "688827.SH",
                "list_date": "2026-11-10",
                "delist_date": None,
            }
        ]
    }
    raw = {"coverage": [{"instrument_id": 7, "canonical_symbol": "688827.SH", "status": status}]}
    with pytest.raises(ValueError, match="identities differ"):
        validate_risk_identities(raw, metadata, date(2026, 11, 10))
    raw["coverage"][0]["instrument_id"] = 42
    validate_risk_identities(raw, metadata, date(2026, 11, 10))


@pytest.mark.anyio
async def test_new_code_can_replay_valid_publication_but_cannot_write_old_artifact(
    monkeypatch, tmp_path
):
    import gr_data.diagnosis_daily as daily
    from gr_data.common.paths import RawPaths

    conn = Mock()
    conn.info.transaction_status = TransactionStatus.INTRANS
    data = {
        "day": "2026-11-06",
        "history_start": "2025-10-22",
        "version_id": "published",
        "importer_version": "old",
    }
    monkeypatch.setattr(daily, "get_importer_version", lambda **kwargs: "new")
    monkeypatch.setattr(daily, "_row", lambda *args: {"valid": True})
    result = await daily._apply(conn, data, {}, RawPaths(tmp_path), Mock())
    assert result["replay"] and result["business_rows_written"] == 0
    monkeypatch.setattr(daily, "_row", lambda *args: None)
    with pytest.raises(ValueError, match="Importer changed"):
        await daily._apply(conn, data, {}, RawPaths(tmp_path), Mock())
    assert not any(
        "INSERT" in str(call) or "UPDATE" in str(call) for call in conn.execute.call_args_list
    )


def test_new_listing_bootstraps_annual_source_with_old_announcement(tmp_path):
    from decimal import Decimal

    import pandas as pd
    from gr_data.common.paths import RawPaths
    from gr_data.diagnosis_daily.collect import collect_annual_backfill
    from gr_data.ingest.tushare.financial import normalize_annual_roe

    class Supplier:
        def query_all(self, endpoint, **params):
            assert endpoint == "fina_indicator" and params["ts_code"] == "688827.SH"
            return pd.DataFrame(
                {
                    "ts_code": ["688827.SH"],
                    "end_date": [params["period"]],
                    "ann_date": ["20260430"],
                    "roe_waa": [20.0],
                    "update_flag": ["1"],
                }
            )

    raw, observed = collect_annual_backfill(
        Supplier(), RawPaths(tmp_path), ["688827.SH"], date(2026, 11, 10)
    )
    frame = normalize_annual_roe(
        raw, symbol_ids={"688827.SH": 42}, as_of=date(2026, 11, 10), observed_at=observed
    )
    assert set(frame["roe"]) == {Decimal(".2")} and frame.height == 2
    latest_announcement = frame["ann_date"].max()
    assert isinstance(latest_announcement, date)
    assert latest_announcement < date(2026, 11, 10)
