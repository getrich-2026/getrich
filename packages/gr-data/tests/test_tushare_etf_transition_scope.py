"""四条身份登记的边界、完整性、写库前门禁及159908迁移回归。"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from typing import cast
from unittest.mock import MagicMock, patch

import pandas as pd
import psycopg
import pytest
from gr_data.common.paths import RawPaths
from gr_data.ingest.base import IngestContext, IngestGateError
from gr_data.ingest.tushare.etf_scope import (
    ETF_IDENTITY_REGISTRY_SHA256,
    ETF_TRANSITION_NOTICE,
    exclude_etf_pre_transition,
    load_etf_identity_registry,
    parse_etf_identity_registry,
)
from gr_data.ingest.tushare.importers.asset_markets import EtfBars1dImporter


def make_importer(tmp_path, codes_and_days, listing_dates):
    rows = pd.DataFrame(
        [
            dict(
                ts_code=code,
                trade_date=day,
                open=1.0,
                high=1.2,
                low=0.9,
                close=1.1,
                pre_close=1.0,
                vol=10,
                amount=20,
            )
            for code, day in codes_and_days
        ]
    )
    factors = rows[["ts_code", "trade_date"]].assign(adj_factor=1.25)
    obj = EtfBars1dImporter(
        cast(psycopg.Connection, None), IngestContext(RawPaths(tmp_path), months=("2018-12",))
    )
    obj._metadata = lambda: pd.DataFrame(
        [{"ts_code": code, "list_date": day} for code, day in listing_dates.items()]
    )
    obj._read = lambda dataset: (rows if dataset == "fund_daily" else factors).copy()
    obj._ids = lambda codes, asset: {code: i + 1 for i, code in enumerate(sorted(codes))}
    return obj, rows, factors


def test_159908_before_transition_excluded_with_both_dataset_receipts(tmp_path):
    obj, rows, factors = make_importer(
        tmp_path,
        [("159908.SZ", "20181207"), ("159908.SZ", "20181210"), ("159908.SZ", "20181211")],
        {"159908.SZ": "20181210"},
    )
    before_rows, before_factors = rows.copy(deep=True), factors.copy(deep=True)
    built = obj.build()
    assert built.dt.tolist() == [date(2018, 12, 10), date(2018, 12, 11)]
    assert built.adj_factor.tolist() == [1.25, 1.25]
    notices = obj.collect_soft_warnings()
    assert len(notices) == 2
    details = [json.loads(w.removeprefix(ETF_TRANSITION_NOTICE)) for w in notices]
    assert {d["dataset"] for d in details} == {"fund_daily", "fund_adj"}
    for detail in details:
        assert detail["ts_code"] == "159908.SZ"
        assert detail["start_date"] == detail["end_date"] == "2018-12-07"
        assert detail["rows"] == 1
        assert detail["reason"] == "基金转型前，不在范围内"
        assert detail["evidence"] == [
            e.url
            for event in load_etf_identity_registry().events
            if event.ts_code == "159908.SZ"
            for e in event.evidence
        ]
        assert detail["registry_sha256"] == ETF_IDENTITY_REGISTRY_SHA256
    pd.testing.assert_frame_equal(rows, before_rows)
    pd.testing.assert_frame_equal(factors, before_factors)
    assert obj._metadata().list_date.tolist() == ["20181210"]


@pytest.mark.parametrize("code", ["159909.SZ", "510681.SH", "512991.SH", "511221.SH"])
def test_other_etf_prelisting_bars_still_stop(tmp_path, code):
    obj, _, _ = make_importer(tmp_path, [(code, "20181207")], {code: "20181210"})
    with pytest.raises(IngestGateError, match="Bar precedes instrument listing"):
        obj.build()
    assert obj.collect_soft_warnings() == []


def test_transition_rule_does_not_hide_later_listing_conflict(tmp_path):
    obj, _, _ = make_importer(tmp_path, [("159908.SZ", "20181210")], {"159908.SZ": "20181211"})
    with pytest.raises(IngestGateError, match="list_date mismatch"):
        obj.build()


def test_only_pretransition_rows_yield_empty_canonical_with_receipts(tmp_path):
    obj, _, _ = make_importer(tmp_path, [("159908.SZ", "20181207")], {"159908.SZ": "20181210"})
    assert obj.build().empty
    assert len(obj.collect_soft_warnings()) == 2


def test_other_etf_values_unchanged_by_transition_filter(tmp_path):
    rows = [("159908.SZ", "20181207"), ("510300.SH", "20181207")]
    obj, _, _ = make_importer(tmp_path, rows, {"159908.SZ": "20181210", "510300.SH": "20120101"})
    baseline, _, _ = make_importer(tmp_path, rows[1:], {"510300.SH": "20120101"})
    pd.testing.assert_frame_equal(obj.build(), baseline.build())


def test_scope_requires_explicit_fund_dataset():
    with pytest.raises(ValueError, match="Unsupported ETF transition dataset"):
        exclude_etf_pre_transition(pd.DataFrame(), "opt_daily")


@pytest.mark.parametrize("event", load_etf_identity_registry().events, ids=lambda e: e.ts_code)
def test_all_four_transition_boundaries_and_independent_receipts(tmp_path, event):
    dates = [event.effective_date + timedelta(days=n) for n in (-1, 0, 1)]
    obj, _, _ = make_importer(
        tmp_path,
        [(event.ts_code, day.strftime("%Y%m%d")) for day in dates],
        {event.ts_code: event.effective_date.strftime("%Y%m%d")},
    )
    assert obj.build().dt.tolist() == dates[1:]
    details = [
        json.loads(w.removeprefix(ETF_TRANSITION_NOTICE)) for w in obj.collect_soft_warnings()
    ]
    assert {d["dataset"] for d in details} == {"fund_daily", "fund_adj"}
    assert all(d["rows"] == 1 and d["event_id"] == event.event_id for d in details)
    assert all(d["registry_sha256"] == ETF_IDENTITY_REGISTRY_SHA256 for d in details)


def registry_document():
    from importlib.resources import files

    return json.loads(
        files("gr_data.ingest.tushare")
        .joinpath("evidence", "etf_identity_events.v1.json")
        .read_bytes()
    )


@pytest.mark.parametrize(
    "damage", ["duplicate", "hash", "evidence_hash", "rename", "manager_change"]
)
def test_invalid_registry_fails_before_ownership_or_business_writes(tmp_path, monkeypatch, damage):
    import gr_data.ingest.tushare.etf_scope as scope

    data = registry_document()
    if damage == "duplicate":
        data["events"].append(dict(data["events"][0]))
    elif damage == "evidence_hash":
        data["events"][0]["evidence"][0]["sha256"] = "not-a-hash"
    elif damage in {"rename", "manager_change"}:
        data["events"][0]["event_type"] = damage
    payload = json.dumps(data).encode()
    expected = "0" * 64 if damage == "hash" else hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(
        "gr_data.ingest.tushare.importers.asset_markets.load_etf_identity_registry",
        lambda: parse_etf_identity_registry(payload, expected),
    )
    obj, _, _ = make_importer(tmp_path, [("510300.SH", "20181210")], {"510300.SH": "20120101"})
    connection = MagicMock()
    obj.conn = connection
    with patch("gr_data.ingest.base.OwnershipManager") as ownership:
        with pytest.raises(IngestGateError):
            obj.run()
        ownership.assert_not_called()
    connection.assert_not_called()
    assert connection.mock_calls == []
    # 真正的资源加载路径同样受源码中固定的SHA保护。
    assert scope.load_etf_identity_registry().sha256 == ETF_IDENTITY_REGISTRY_SHA256


def test_metadata_date_mismatch_fails_before_any_write(tmp_path, monkeypatch):
    obj, _, _ = make_importer(tmp_path, [("510680.SH", "20151215")], {"510680.SH": "20151216"})
    monkeypatch.setattr(
        "gr_data.ingest.tushare.importers.asset_markets.asset_metadata",
        lambda *args, **kwargs: obj._metadata(),
    )
    connection = MagicMock()
    obj.conn = connection
    with patch("gr_data.ingest.base.OwnershipManager") as ownership:
        with pytest.raises(IngestGateError, match="list_date mismatch"):
            obj.run()
        ownership.assert_not_called()
    assert connection.mock_calls == []


def test_resource_payload_tampering_is_rejected_even_when_json_is_valid():
    payload = json.dumps(registry_document()).encode()
    with pytest.raises(IngestGateError, match="SHA256 mismatch"):
        parse_etf_identity_registry(payload, ETF_IDENTITY_REGISTRY_SHA256)


def test_registry_contains_only_the_four_approved_codes():
    assert {e.ts_code for e in load_etf_identity_registry().events} == {
        "159908.SZ",
        "510680.SH",
        "512990.SH",
        "511220.SH",
    }
