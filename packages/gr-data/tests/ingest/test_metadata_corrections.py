"""已核实日期的旧快照、供应商纠正、新冲突及失败留证回归。"""

from __future__ import annotations

import copy
import json
from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest
from gr_data.common.paths import RawPaths
from gr_data.ingest.base import IngestGateError
from gr_data.ingest.tushare import metadata_corrections as guard


@pytest.fixture
def evidence(monkeypatch):
    audit = {
        "symbol": "FU1807.SHF",
        "instrument_id": 41,
        "plan_sha256": "p" * 64,
        "before": {"delist_date": "2018-06-28"},
        "after": {"delist_date": "2018-06-26"},
    }
    record = {
        "symbol": "FU1807.SHF",
        "asset": "future",
        "exchange": "SHFE",
        "rule": "verified_fixture",
        "plan_sha256": audit["plan_sha256"],
        "audit_detail_sha256": guard._digest(audit),
        "original_date": "2018-06-28",
        "verified_date": "2018-06-26",
        "list_date": "2017-07-03",
    }
    monkeypatch.setattr(guard, "_registry", lambda: {record["symbol"]: record})
    identity = (
        "FU1807.SHF",
        41,
        "future",
        "SHFE",
        date(2017, 7, 3),
        date(2018, 6, 26),
        None,
        None,
        "FU1807.SHF",
    )
    return record, audit, identity


def connection(audits, identities):
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.side_effect = [audits, identities]
    return conn


def raw(**overrides):
    return pd.DataFrame(
        [
            {
                "ts_code": "FU1807.SHF",
                "exchange": "SHFE",
                "list_date": "20170703",
                "delist_date": "20180628",
                "name": "旧燃料油",
                **overrides,
            }
        ]
    )


def test_old_snapshot_preserves_verified_date_without_mutating_raw(evidence, tmp_path):
    record, audit, identity = evidence
    source = raw()
    before = source.copy(deep=True)
    out = guard.protect_metadata_dates(
        connection([(record["rule"], audit)], [identity]), RawPaths(tmp_path), source, "future"
    )
    assert out.loc[0, "delist_date"] == "20180626"
    assert out.loc[0, "name"] == "旧燃料油"
    pd.testing.assert_frame_equal(source, before)
    assert not list(tmp_path.rglob("receipt.json"))


def test_supplier_already_correct_returns_original(evidence, tmp_path):
    record, audit, identity = evidence
    source = raw(delist_date="20180626")
    out = guard.protect_metadata_dates(
        connection([(record["rule"], audit)], [identity]), RawPaths(tmp_path), source, "future"
    )
    assert out is source


@pytest.mark.parametrize(
    "updates,failure",
    [
        ({"delist_date": "20180627"}, "new_supplier_last_trade_date_conflict"),
        ({"delist_date": None}, "new_supplier_last_trade_date_conflict"),
        ({"delist_date": "bad"}, "invalid_supplier_lifecycle_date"),
        ({"list_date": "20170704"}, "supplier_lifecycle_identity_changed"),
        ({"exchange": "DCE"}, "supplier_exchange_changed"),
    ],
)
def test_new_conflict_is_preserved_before_gate(evidence, tmp_path, updates, failure):
    record, audit, identity = evidence
    source = raw(**updates)
    with pytest.raises(IngestGateError, match="evidence="):
        guard.protect_metadata_dates(
            connection([(record["rule"], audit)], [identity]), RawPaths(tmp_path), source, "future"
        )
    receipts = list(tmp_path.rglob("receipt.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text())
    assert receipt["issues"][0]["failure"] == failure
    pd.testing.assert_frame_equal(
        pd.read_parquet(receipts[0].parent / "source_rows.parquet"), source
    )


@pytest.mark.parametrize(
    "mode", ["missing", "duplicate", "tampered", "unmapped", "wrong_id", "stored_date"]
)
def test_unverified_audit_or_identity_fails(evidence, tmp_path, mode):
    record, audit, identity = evidence
    audits = [(record["rule"], copy.deepcopy(audit))]
    identities = [identity]
    if mode == "missing":
        audits = []
    elif mode == "duplicate":
        audits *= 2
    elif mode == "tampered":
        audits[0][1]["after"]["delist_date"] = "2018-06-25"
    elif mode == "unmapped":
        identities = []
    elif mode == "wrong_id":
        identities = [(identity[0], 999, *identity[2:])]
    else:
        identities = [(*identity[:5], date(2018, 6, 28), *identity[6:])]
    with pytest.raises(IngestGateError):
        guard.protect_metadata_dates(
            connection(audits, identities), RawPaths(tmp_path), raw(), "future"
        )


def test_unregistered_and_other_asset_do_not_query(evidence, tmp_path):
    conn = MagicMock()
    source = raw(ts_code="FU1806.SHF")
    assert guard.protect_metadata_dates(conn, RawPaths(tmp_path), source, "future") is source
    assert guard.protect_metadata_dates(conn, RawPaths(tmp_path), raw(), "etf") is not None
    conn.cursor.assert_not_called()


@pytest.mark.parametrize("incoming", ["20250528", "20250328", "20250331"])
def test_option_date_protection_preserves_planned_maturity(monkeypatch, tmp_path, incoming):
    audit = {"symbol": "90005271.SZ", "instrument_id": 52, "plan_sha256": "p" * 64}
    record = {
        "symbol": audit["symbol"],
        "asset": "option",
        "exchange": "XSHE",
        "rule": "fixture",
        "plan_sha256": audit["plan_sha256"],
        "audit_detail_sha256": guard._digest(audit),
        "original_date": "2025-05-28",
        "verified_date": "2025-03-28",
        "list_date": "2025-03-27",
        "maturity_date": "2025-05-28",
    }
    monkeypatch.setattr(guard, "_registry", lambda: {record["symbol"]: record})
    identity = (
        record["symbol"],
        52,
        "option",
        "XSHE",
        date(2025, 3, 27),
        date(2025, 3, 28),
        date(2025, 3, 28),
        date(2025, 5, 28),
        record["symbol"],
    )
    source = pd.DataFrame(
        [
            {
                "ts_code": record["symbol"],
                "exchange": "SZSE",
                "list_date": "20250327",
                "delist_date": incoming,
                "maturity_date": "20250528",
            }
        ]
    )
    conn = connection([("fixture", audit)], [identity])
    if incoming == "20250331":
        with pytest.raises(IngestGateError):
            guard.protect_metadata_dates(conn, RawPaths(tmp_path), source, "option")
    else:
        out = guard.protect_metadata_dates(conn, RawPaths(tmp_path), source, "option")
        assert out.loc[0, "delist_date"] == "20250328"
        assert out.loc[0, "maturity_date"] == "20250528"


def test_real_registry_is_closed_and_pinned():
    records = guard._registry()
    assert len(records) == 14
    assert sum(len(r["target_fields"]) for r in records.values()) == 16
    assert set(records) == {
        *(f"FU18{m:02}.SHF" for m in range(7, 13)),
        "WR1809.SHF",
        "WR1810.SHF",
        "WR1811.SHF",
        "WR1812.SHF",
        "WR1901.SHF",
        "WR1902.SHF",
        "90005271.SZ",
        "90005272.SZ",
    }


def test_future_importer_does_not_drop_conflict_before_guard(evidence, tmp_path):
    from gr_data.ingest.base import IngestContext
    from gr_data.ingest.tushare.importers.reference import InstrumentsImporter

    record, audit, identity = evidence
    source = pd.concat([raw(delist_date="20180627"), raw()], ignore_index=True)
    importer = InstrumentsImporter(
        connection([(record["rule"], audit)], [identity]), IngestContext(RawPaths(tmp_path))
    )
    with pytest.raises(IngestGateError):
        importer._build_future(source)
    receipt = next(tmp_path.rglob("receipt.json"))
    assert len(pd.read_parquet(receipt.parent / "source_rows.parquet")) == 2


@pytest.mark.parametrize("incoming", ["20250326", "bad"])
def test_option_importer_keeps_date_conflict_before_old_validation(monkeypatch, tmp_path, incoming):
    from gr_data.ingest.base import IngestContext
    from gr_data.ingest.tushare.importers import asset_markets

    audit = {"symbol": "90005271.SZ", "instrument_id": 52, "plan_sha256": "p" * 64}
    record = {
        "symbol": audit["symbol"],
        "asset": "option",
        "exchange": "XSHE",
        "rule": "fixture",
        "plan_sha256": audit["plan_sha256"],
        "audit_detail_sha256": guard._digest(audit),
        "original_date": "2025-05-28",
        "verified_date": "2025-03-28",
        "list_date": "2025-03-27",
        "maturity_date": "2025-05-28",
    }
    monkeypatch.setattr(guard, "_registry", lambda: {record["symbol"]: record})
    source = pd.DataFrame(
        [
            {
                "ts_code": record["symbol"],
                "exchange": "SZSE",
                "list_date": "20250327",
                "delist_date": incoming,
                "maturity_date": "20250528",
            }
        ]
    )
    monkeypatch.setattr(asset_markets, "read_asset_observation", lambda path: (source, {}))
    identity = (
        record["symbol"],
        52,
        "option",
        "XSHE",
        date(2025, 3, 27),
        date(2025, 3, 28),
        date(2025, 3, 28),
        date(2025, 5, 28),
        record["symbol"],
    )
    importer = asset_markets.OptionInstrumentsImporter(
        connection([("fixture", audit)], [identity]),
        IngestContext(RawPaths(tmp_path)),
        validation_only=True,
    )
    with pytest.raises(IngestGateError):
        importer.build()
    receipt = next(tmp_path.rglob("receipt.json"))
    assert pd.read_parquet(receipt.parent / "source_rows.parquet").loc[0, "delist_date"] == incoming
