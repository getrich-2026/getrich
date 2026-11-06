"""封闭的四十合约补充：来源断言、生命周期、恢复比对及原始响应隔离。"""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import MagicMock

import pandas as pd
import pytest
from gr_data.common.retry import PermanentError
from gr_data.ingest.tushare import czce_metadata as glue
from gr_data.raw.czce import metadata as m
from gr_data.raw.tushare.context import TushareRawContext
from gr_data.raw.tushare.fetchers import asset_markets as fetchers
from gr_data.raw.tushare.fetchers.asset_markets import OptionInstrumentsFetcher


def meta(code="CJ612C11000.ZCE", **changes):
    row = dict(
        ts_code=code,
        symbol=code.removesuffix(".ZCE"),
        exchange="CZCE",
        name="测试合约",
        opt_code="OPCJ2612.ZCE",
        opt_type="期货期权",
        call_put="C",
        exercise_type="美式",
        exercise_price=11000.0,
        per_unit=5.0,
        opt_multiplier=5.0,
        s_month="202612",
        maturity_date="20261028",
        list_price=12.5,
        list_date="20260401",
        delist_date="20261028",
        last_edate=None,
        last_ddate=None,
        quote_unit="人民币元/吨",
        min_price_chg="1.0",
    )
    row.update(changes)
    return row


def prices(code="CJ612C11200.ZCE", day=m.FIRST, **changes):
    row = dict(
        ts_code=code,
        trade_date=day,
        exchange="CZCE",
        open=199.0,
        high=200.0,
        low=197.0,
        close=200.0,
        settle=196.0,
        pre_settle=179.0,
        vol=28.0,
        oi=28.0,
        amount=2.77,
    )
    row.update(changes)
    return row


@pytest.fixture
def inputs():
    reference = [meta()]
    daily = {
        m.FIRST: pd.DataFrame([prices()]),
        m.PREVIOUS: pd.DataFrame([prices("AP610C10000.ZCE", m.PREVIOUS)]),
    }
    for i, day in enumerate(m.CALIBRATION_DAYS):
        code = f"AP610C{10000 + i * 200}.ZCE"
        reference.append(
            meta(
                code,
                opt_code="OPAP2610.ZCE",
                exercise_price=10000 + i * 200,
                list_date=day,
                list_price=12.5,
            )
        )
        daily[day] = pd.DataFrame([prices(code, day, pre_settle=12.5)])
    observed = pd.DataFrame([prices(), prices(day="20261028")])
    evidence = {d: "a" * 64 for d in {*m.CALIBRATION_DAYS, m.FIRST}}
    evidence.update(reference="b" * 64, observed="c" * 64)
    return pd.DataFrame(reference), daily, observed, frozenset(["CJ612C11200.ZCE"]), evidence


def derive(values):
    return m.derive(*values)


def supplement(values):
    frame, _ = derive(values)
    obj = object.__new__(m.MetadataSupplement)
    obj.frame = frame
    obj.by_code = frame.set_index("ts_code", drop=False)
    obj.manifest_sha256 = "d" * 64
    obj.manifest = {"evidence_sha256": values[-1]}
    return obj


def test_official_metadata_fields_and_sources(inputs):
    frame, checks = derive(inputs)
    row = frame.iloc[0]
    assert row.ts_code == "CJ612C11200.ZCE" and row.symbol == "CJ612C11200"
    assert row.call_put == "C" and row.exercise_price == Decimal(11200)
    assert row.list_date == m.FIRST and row.list_price == Decimal(179) and row["name"] is None
    assert checks["code_calibration_rows"] == 4 and checks["list_price_calibration_rows"] == 3
    assert set(json.loads(row.field_sources)) == set(m.FIELDS)
    assert json.loads(row.field_sources)["list_price"]["sha256"] == "a" * 64


@pytest.mark.parametrize("field", m.COPY_FIELDS)
def test_sibling_disagreement_stops(inputs, field):
    reference, *_ = inputs
    sibling = meta("CJ612P11000.ZCE", call_put="P")
    sibling[field] = "20261029" if field == "delist_date" else "different"
    inputs[0].loc[len(reference)] = sibling
    with pytest.raises(ValueError, match=f"sibling field.*{field}"):
        derive(inputs)


def test_no_sibling_stops(inputs):
    reference, daily, observed, codes, evidence = inputs
    with pytest.raises(ValueError, match="Missing CZCE sibling"):
        derive((reference.iloc[1:], daily, observed, codes, evidence))


@pytest.mark.parametrize("field,value", [("call_put", "P"), ("exercise_price", 999)])
def test_code_calibration_mismatch_stops(inputs, field, value):
    inputs[0].loc[0, field] = value
    with pytest.raises(ValueError, match="code calibration mismatch"):
        derive(inputs)


def test_list_price_calibration_mismatch_stops(inputs):
    inputs[0].loc[1, "list_price"] = 12.51
    with pytest.raises(ValueError, match="list price calibration mismatch"):
        derive(inputs)


def test_previous_day_presence_stops(inputs):
    inputs[1][m.PREVIOUS] = pd.concat(
        [inputs[1][m.PREVIOUS], pd.DataFrame([prices(day=m.PREVIOUS)])], ignore_index=True
    )
    with pytest.raises(ValueError, match="present before listing"):
        derive(inputs)


def test_first_day_price_mismatch_stops(inputs):
    inputs[1][m.FIRST].loc[0, "amount"] = 2.78
    with pytest.raises(ValueError, match="first-day prices mismatch.*amount"):
        derive(inputs)


def test_monthly_and_old_decade_not_siblings():
    reference = pd.DataFrame(
        [
            meta(
                "SR707C5000.ZCE",
                opt_code="OPSR2707.ZCE",
                list_date="20260601",
                delist_date="20270601",
            ),
            meta(
                "SR707P5000.ZCE",
                opt_code="OPSR1707.ZCE",
                list_date="20160601",
                delist_date="20170601",
            ),
            meta(
                "SR707MSC5000.ZCE",
                opt_code="OPSR2707.ZCE",
                list_date="20260601",
                delist_date="20270601",
                per_unit=999,
            ),
        ]
    )
    fields, codes = m.group_values(reference, "SR707", "20260601", "20261105")
    assert codes == ["SR707C5000.ZCE"] and fields["opt_code"] == "OPSR2707.ZCE"


def test_current_siblings_disagree_or_missing_stop(inputs):
    obj = supplement(inputs)
    with pytest.raises(ValueError, match="Missing CZCE sibling"):
        obj.assert_siblings(inputs[0].iloc[1:], "CJ612C11200.ZCE")
    wrong = pd.DataFrame([meta(per_unit=6)])
    with pytest.raises(ValueError, match="Current CZCE sibling differs.*per_unit"):
        obj.assert_siblings(wrong, "CJ612C11200.ZCE")


def test_tushare_restoration_uses_original_row(inputs):
    obj = supplement(inputs)
    restored = obj.frame[list(m.FIELDS)].copy()
    restored["name"] = "供应商恢复名称"
    restored["list_date"] = "20260528"
    restored["list_price"] = 179.0
    merged = obj.merge(restored)
    pd.testing.assert_frame_equal(merged, restored)
    assert merged.iloc[0]["name"] == "供应商恢复名称"


@pytest.mark.parametrize(
    "field,value",
    [
        ("list_price", 179.01),
        ("exercise_price", 11201),
        ("last_edate", "20261029"),
        ("min_price_chg", "0.5"),
    ],
)
def test_tushare_restoration_disagreement_stops(inputs, field, value):
    obj = supplement(inputs)
    restored = obj.frame[list(m.FIELDS)].copy()
    restored.loc[0, field] = value
    with pytest.raises(ValueError, match=f"Restored CZCE metadata differs.*{field}"):
        obj.merge(restored)


def test_missing_both_is_allowed_but_one_side_missing_stops(inputs):
    obj = supplement(inputs)
    restored = obj.frame[list(m.FIELDS)].copy()
    obj.compare_tushare(restored)
    restored.loc[0, "last_edate"] = "20261028"
    with pytest.raises(ValueError, match="last_edate"):
        obj.compare_tushare(restored)


def test_monthly_report_count_samples_and_provenance(inputs):
    obj = supplement(inputs)
    reports = obj.reports(inputs[2], inputs[0], "2026-05")
    assert len(reports) == 1
    assert reports[0]["code_count"] == 1 and reports[0]["codes"] == ["CJ612C11200.ZCE"]
    assert reports[0]["samples"] == ["CJ612C11200.ZCE"]
    assert reports[0]["evidence_sha256"] == inputs[-1]


def test_fetch_fallback_never_enters_tushare_compatibility_result(
    inputs, tmp_raw_root, monkeypatch, tmp_path
):
    obj = supplement(inputs)
    sibling = pd.DataFrame([meta()])
    requests = []

    class Client:
        def query_all(self, api, **params):
            requests.append(params)
            return pd.DataFrame() if "ts_code" in params else sibling.copy()

    monkeypatch.setattr(fetchers, "MetadataSupplement", lambda _paths: obj)
    fetcher = OptionInstrumentsFetcher(Client(), TushareRawContext(paths=tmp_raw_root))
    frame, stats, responses = fetcher._batches(["CJ612C11200.ZCE"], pd.DataFrame(), tmp_path)
    assert frame.empty
    assert stats["official_metadata_supplement_codes"] == ["CJ612C11200.ZCE"]
    assert [r.get("ts_code") for r in requests] == ["CJ612C11200.ZCE", None]
    assert len(responses) == 2 and pd.read_parquet(responses[0]).empty


def test_unlisted_missing_code_still_stops(tmp_raw_root, tmp_path):
    client = MagicMock()
    client.query_all.return_value = pd.DataFrame()
    fetcher = OptionInstrumentsFetcher(client, TushareRawContext(paths=tmp_raw_root))
    with pytest.raises(PermanentError, match="Unresolved option metadata code=CJ612C11400.ZCE"):
        fetcher._batches(["CJ612C11400.ZCE"], pd.DataFrame(), tmp_path)


def test_audit_shares_connection_without_commit(inputs):
    obj = supplement(inputs)
    reports = obj.reports(inputs[2], inputs[0], "2026-05")
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    glue.record_audit(conn, reports, "market.option_bar_1d")
    assert not conn.commit.called and not conn.rollback.called
    calls = conn.cursor.return_value.__enter__.return_value.execute.call_args_list
    assert any("pg_advisory_xact_lock" in call.args[0] for call in calls)
    assert any("INSERT INTO ops.data_quality_check" in call.args[0] for call in calls)


@pytest.mark.parametrize("wrong_day", [False, True])
def test_parse_daily_original_txt(tmp_path, wrong_day):
    p = tmp_path / "OptionDataDaily.txt"
    p.write_text(
        "郑州商品交易所期权每日行情表(2026-05-29)\n合约代码|昨结算|今开盘|最高价|最低价|今收盘|今结算|成交量(手)|持仓量|成交额(万元)\nCJ612C11200|179|199|200|197|200|196|1,000|28|--\n总计|||||||1,000|28|--\n"
    )
    if wrong_day:
        with pytest.raises(ValueError, match="date mismatch"):
            m.parse_daily(p, "20260528")
    else:
        frame = m.parse_daily(p, m.FIRST)
        assert frame.iloc[0].vol == 1000 and frame.iloc[0].amount is None


def test_empty_official_first_list_price_stops(inputs):
    inputs[1][m.FIRST].loc[0, "pre_settle"] = None
    with pytest.raises(ValueError, match="Missing CZCE first-day list price"):
        derive(inputs)


@pytest.mark.parametrize("damage", [None, "count", "code", "hash", "month", "bool", "underlying"])
def test_notice_only_recognizes_approved_shape(inputs, monkeypatch, damage):
    obj = supplement(inputs)
    report = obj.reports(inputs[2], inputs[0], "2026-05")[0]
    monkeypatch.setattr(
        m,
        "policy",
        lambda: {
            "manifest_sha256": obj.manifest_sha256,
            "evidence_sha256": inputs[-1],
            "groups": {"OPCJ2612.ZCE": ["CJ612C11200.ZCE"]},
        },
    )
    if damage == "count":
        report["code_count"] = 2
    elif damage == "code":
        report["codes"] = ["CJ612C11400.ZCE"]
    elif damage == "hash":
        report["manifest_sha256"] = "e" * 64
    elif damage == "month":
        report["month"] = "2026-13"
    elif damage == "bool":
        report["code_count"] = True
    elif damage == "underlying":
        report["opt_code"] = "OPCJ2712.ZCE"
    assert (m.parse_notice(m.NOTICE + json.dumps(report)) is not None) == (damage is None)


def test_full_fetch_receipt_archive_and_restoration_are_separate(inputs, tmp_raw_root, monkeypatch):
    from gr_data.raw.tushare.asset_rules import read_asset_observation

    obj = supplement(inputs)
    obj.root = tmp_raw_root.dataset_dir("czce", m.DATASET)
    monkeypatch.setattr(fetchers, "MetadataSupplement", lambda _paths: obj)
    standard = pd.DataFrame([meta()])
    ctx = TushareRawContext(
        paths=tmp_raw_root, start_date=20260529, end_date=20260529, option_exchanges=("CZCE",)
    )
    client = MagicMock()
    alias = dict(meta(), ts_code="CJ612C11000.ZCE2")
    client.query_all.side_effect = lambda api, **params: (
        pd.DataFrame() if "ts_code" in params else pd.DataFrame([meta(), alias])
    )
    daily_writer = OptionInstrumentsFetcher(client, ctx)
    daily_writer.DATASET = "opt_daily"
    daily_writer._publish(
        inputs[2].iloc[:1],
        tmp_raw_root.dataset_file("tushare", "opt_daily", "2026-05"),
        {"start": "2026-05-29", "end": "2026-05-29", "exchanges": ["CZCE"], "pending_days": []},
    )
    writer = OptionInstrumentsFetcher(client, ctx)
    path = tmp_raw_root.dataset_file("tushare", "instruments", "option")
    writer._publish(standard, path, {"coverage": "observed_daily_codes"})
    before = pd.read_parquet(path)
    writer.fetch("update")
    actual, receipt = read_asset_observation(path)
    pd.testing.assert_frame_equal(actual, before)
    assert receipt["scope"]["official_metadata_supplement_codes"] == ["CJ612C11200.ZCE"]
    assert receipt["scope"]["duplicate_metadata_rows"][0]["rows"] == 1
    month = json.loads((obj.root / "receipts/2026-05.json").read_text())
    assert month["reports"][0]["code_count"] == 1
    archive = (
        tmp_raw_root.dataset_dir("tushare", "observations")
        / "option_instruments"
        / receipt["observation_id"]
    )
    assert pd.read_parquet(archive / receipt["source_responses"][0]["file"]).empty
    assert set(pd.read_parquet(archive / receipt["source_responses"][1]["file"]).ts_code) == {
        "CJ612C11000.ZCE",
        "CJ612C11000.ZCE2",
    }
    restored = obj.frame[list(m.FIELDS)].copy()
    restored["name"] = "Tushare recovered"
    restored["list_date"] = "20260528"
    restored["exercise_price"] = restored["exercise_price"].astype(float)
    restored["list_price"] = restored["list_price"].astype(float)
    client.query_all.side_effect = lambda api, **params: (
        restored.copy()
        if "ts_code" in params
        else pd.concat([standard, restored], ignore_index=True)
    )
    writer.fetch("update")
    actual, _ = read_asset_observation(path)
    assert actual.loc[actual.ts_code.eq("CJ612C11200.ZCE"), "name"].item() == "Tushare recovered"
    assert (
        json.loads((obj.root / "receipts/2026-05.json").read_text())["reports"][0]["code_count"]
        == 0
    )
    before = path.read_bytes()
    restored["list_price"] = 180
    with pytest.raises(ValueError, match="Restored CZCE metadata differs.*list_price"):
        writer.fetch("update")
    assert path.read_bytes() == before


@pytest.mark.parametrize("damage", ["manifest", "file"])
def test_supplement_evidence_hash_mismatch_stops(tmp_raw_root, monkeypatch, damage):
    import hashlib

    root = tmp_raw_root.dataset_dir("czce", m.DATASET)
    root.mkdir(parents=True)
    codes = sorted(m.approved_codes())
    manifest = {
        "rule": m.RULE,
        "codes": codes,
        "files": [{"path": "evidence.txt", "sha256": "a" * 64}],
    }
    (root / "evidence.txt").write_text("changed")
    p = root / "manifest.json"
    p.write_text(json.dumps(manifest))
    pin = hashlib.sha256(p.read_bytes()).hexdigest() if damage == "file" else "b" * 64
    monkeypatch.setattr(m, "policy", lambda: {"codes": codes, "manifest_sha256": pin})
    with pytest.raises(ValueError, match="changed approved|Changed CZCE"):
        m.MetadataSupplement(tmp_raw_root)


@pytest.mark.parametrize("damage", ["no_standard", "field_diff"])
def test_supplement_does_not_relax_duplicate_alias_gate(
    inputs, tmp_raw_root, tmp_path, monkeypatch, damage
):
    obj = supplement(inputs)
    monkeypatch.setattr(fetchers, "MetadataSupplement", lambda _paths: obj)
    if damage == "no_standard":
        alias = obj.frame[list(m.FIELDS)].iloc[0].to_dict()
        alias["ts_code"] += "2"
        alias["exercise_price"] = float(alias["exercise_price"])
        alias["list_price"] = float(alias["list_price"])
        batch = pd.DataFrame([meta(), alias])
    else:
        batch = pd.DataFrame([meta(), meta("CJ612C11000.ZCE2", name="different")])
    client = MagicMock()
    client.query_all.side_effect = lambda api, **params: (
        pd.DataFrame() if "ts_code" in params else batch.copy()
    )
    fetcher = OptionInstrumentsFetcher(client, TushareRawContext(paths=tmp_raw_root))
    with pytest.raises(ValueError, match="duplicate_missing_standard|duplicate_field_mismatch"):
        fetcher._batches(["CJ612C11200.ZCE"], pd.DataFrame(), tmp_path)
