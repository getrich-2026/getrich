"""两条跨代重复行情的封闭核销回归。"""

from __future__ import annotations

import pandas as pd
import pytest
from gr_data.ingest.tushare.czce_bar_duplicates import reconcile


def fixture():
    rows = []
    meta = []
    for cp in ["C", "P"]:
        old = f"SR707{cp}6000.ZCE"
        new = f"SR2707{cp}6000.ZCE"
        row = dict(
            trade_date="20260902",
            exchange="CZCE",
            open=1.0,
            high=2.0,
            low=1.0,
            close=1.5,
            vol=0,
            amount=0,
            pre_close=None,
        )
        rows.extend([dict(row, ts_code=old), dict(row, ts_code=new)])
        for code, first, last, underlying in [
            (old, "20170428", "20170523", "OPSR1707.ZCE"),
            (new, "20260902", "20270611", "OPSR2707.ZCE"),
        ]:
            meta.append(
                dict(
                    ts_code=code,
                    symbol=f"SR707{cp}6000",
                    exchange="CZCE",
                    call_put=cp,
                    exercise_price=6000,
                    list_date=first,
                    delist_date=last,
                    opt_code=underlying,
                )
            )
    return pd.DataFrame(rows), pd.DataFrame(meta)


def test_two_pairs(monkeypatch):
    raw, meta = fixture()
    before = raw.copy(deep=True)
    out, reports = reconcile(raw, meta, evidence={"sha256": "a" * 64})
    assert len(out) == 2 and len(reports) == 2
    assert set(out.ts_code) == {"SR2707C6000.ZCE", "SR2707P6000.ZCE"}
    pd.testing.assert_frame_equal(raw, before)


@pytest.mark.parametrize(
    "damage",
    ["missing_new", "value", "duplicate", "identity", "metadata_duplicate", "expiry", "underlying"],
)
def test_bad_pairs_stop(damage):
    raw, meta = fixture()
    if damage == "missing_new":
        raw = raw.iloc[[0, 2, 3]]
    elif damage == "value":
        raw.loc[1, "vol"] = 1
    elif damage == "duplicate":
        raw = pd.concat([raw, raw.iloc[[0]]], ignore_index=True)
    elif damage == "identity":
        meta.loc[1, "symbol"] = "wrong"
    elif damage == "metadata_duplicate":
        meta = pd.concat([meta, meta.iloc[[1]]], ignore_index=True)
    elif damage == "expiry":
        meta.loc[1, "delist_date"] = "20260831"
    elif damage == "underlying":
        meta.loc[1, "opt_code"] = "OPSR1707.ZCE"
    with pytest.raises(ValueError):
        reconcile(raw, meta, evidence={"sha256": "a" * 64})


@pytest.mark.parametrize(
    "field,value",
    [
        ("trade_date", "20170502"),
        ("trade_date", "20260903"),
        ("exchange", "DCE"),
        ("ts_code", "SR707C6100.ZCE"),
    ],
)
def test_outside_scope_unchanged(field, value):
    raw, meta = fixture()
    raw[field] = value
    out, reports = reconcile(raw, meta, evidence={"sha256": "a" * 64})
    pd.testing.assert_frame_equal(out, raw)
    assert reports == []


def test_supplier_fixed_no_cancellation():
    raw, meta = fixture()
    raw = raw[raw.ts_code.str.startswith("SR2707")]
    out, reports = reconcile(raw, meta, evidence={"sha256": "a" * 64})
    pd.testing.assert_frame_equal(out, raw)
    assert reports == []


@pytest.mark.parametrize("damage", ["missing", "hash"])
def test_evidence_fails_closed(tmp_raw_root, damage):
    from gr_data.ingest.tushare.czce_bar_duplicates import load_evidence

    root = tmp_raw_root.dataset_dir("czce", "option_bar_duplicates_v1")
    root.mkdir(parents=True)
    if damage == "hash":
        (root / "manifest.json").write_text("{}")
    with pytest.raises((ValueError, FileNotFoundError)):
        load_evidence(tmp_raw_root)


def test_accounting_and_notice_tamper():
    import json

    from gr_data.ingest.tushare.czce_bar_duplicates import (
        MANIFEST_SHA256,
        NOTICE,
        OFFICIAL_SHA256,
        parse_notice,
        verify_accounting,
    )

    raw, meta = fixture()
    view, reports = reconcile(
        raw, meta, evidence={"sha256": OFFICIAL_SHA256, "manifest_sha256": MANIFEST_SHA256}
    )
    verify_accounting(raw, view, reports)
    assert parse_notice(NOTICE + json.dumps(reports[0])) == reports[0]
    with pytest.raises(ValueError):
        verify_accounting(raw, view, reports[:1])
    reports[0]["rows"] = True
    assert parse_notice(NOTICE + json.dumps(reports[0])) is None


def test_audit_idempotence_same_transaction():
    from unittest.mock import MagicMock

    from gr_data.ingest.tushare.czce_bar_duplicates import record_audit

    raw, meta = fixture()
    _, reports = reconcile(raw, meta, evidence={"sha256": "a" * 64})
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [None, None, (1,), (1,)]
    record_audit(conn, reports, "market.option_bar_1d")
    record_audit(conn, reports, "market.option_bar_1d")
    assert (
        sum(
            "INSERT INTO ops.data_quality_check" in c.args[0] for c in cursor.execute.call_args_list
        )
        == 2
    )
    conn.commit.assert_not_called()
    conn.rollback.assert_not_called()


@pytest.mark.parametrize("damage", ["missing_new", "value", "bool", "null_representation"])
def test_independent_accounting_checks_explanation(damage):
    from gr_data.ingest.tushare.czce_bar_duplicates import (
        MANIFEST_SHA256,
        OFFICIAL_SHA256,
        verify_accounting,
    )

    raw, meta = fixture()
    if damage == "null_representation":
        raw["extra"] = pd.Series([None, pd.NA, None, pd.NA], dtype=object)
    view, reports = reconcile(
        raw, meta, evidence={"sha256": OFFICIAL_SHA256, "manifest_sha256": MANIFEST_SHA256}
    )
    if damage == "missing_new":
        raw = raw.drop(index=1)
        view = view.drop(index=1)
    elif damage == "value":
        raw.loc[1, "vol"] = 1
        view.loc[1, "vol"] = 1
    elif damage == "bool":
        reports[0]["rows"] = True
    if damage == "null_representation":
        verify_accounting(raw, view, reports)
    else:
        with pytest.raises(ValueError):
            verify_accounting(raw, view, reports)
