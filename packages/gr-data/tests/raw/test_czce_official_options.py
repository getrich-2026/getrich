"""郑商所官方字段覆盖的精确范围、解析和断言回归。"""

from __future__ import annotations

import json
from decimal import Decimal

import pandas as pd
import polars as pl
import pytest
from gr_data.raw.czce.options import (
    ASSERT_FIELDS,
    FIRST,
    LAST,
    NUMERIC,
    RULE,
    VALUE_FIELDS,
    OfficialOptionHistory,
    atomic_json,
    atomic_parquet,
    digest,
    parse_option_txt,
)


def row(day="20170822", code="SR801C6200.ZCE", **changes):
    return {
        "trade_date": day,
        "ts_code": code,
        "exchange": "CZCE",
        "open": 10.0,
        "high": 12.0,
        "low": 9.0,
        "close": 11.0,
        "pre_close": 10.5,
        "pre_settle": 10.0,
        "settle": 11.0,
        "vol": 2.0,
        "oi": 4.0,
        "amount": 0.5,
        **changes,
    }


def setup_history(paths, official):
    root = paths.dataset_dir("czce", "option_official_annual")
    frames = {}
    for item in official:
        frames.setdefault(item["trade_date"][:4], []).append(item)
    years = {}
    for year, rows in frames.items():
        frame = pl.from_pandas(pd.DataFrame(rows)).select(
            "ts_code", "trade_date", "exchange", *[pl.col(k).cast(NUMERIC) for k in VALUE_FIELDS]
        )
        frame = frame.with_columns(pl.col("vol").cast(pl.Int64), pl.col("oi").cast(pl.Int64))
        p = root / (year + ".parquet")
        atomic_parquet(p, frame)
        years[year] = {
            "sources": [],
            "rows": len(rows),
            "parquet": {"path": p.name, "sha256": digest(p)},
        }
    atomic_json(root / "manifest.json", {"rule": RULE, "coverage": [FIRST, LAST], "years": years})
    return OfficialOptionHistory(paths, digest(root / "manifest.json"))


@pytest.mark.parametrize("code_header", ["品种代码", "合约代码"])
@pytest.mark.parametrize("oi_header", ["空盘量", "持仓量"])
def test_parse_aliases_thousands_null_and_native_codes(tmp_path, code_header, oi_header):
    p = tmp_path / "official.txt"
    p.write_text(
        "郑商所期权\n"
        + f"交易日期|{code_header}|昨结算|今开盘|最高价|最低价|今收盘|今结算|"
        + f"成交量(手)|{oi_header}|成交额(万元)\n"
        + "2025-05-06|SR507MSC5300|1,000.50|--|—||1,010.00|1,005.50|2,000|3,000|1,234.56\n"
    )
    frame = parse_option_txt(p)
    assert frame["ts_code"][0] == "SR507MSC5300.ZCE"
    assert frame["trade_date"][0] == "20250506"
    assert frame["pre_settle"][0] == Decimal("1000.50")
    assert frame["open"][0] is None and frame["high"][0] is None and frame["low"][0] is None
    assert frame["vol"][0] == 2000 and frame["oi"][0] == 3000
    assert frame["amount"][0] == Decimal("1234.56")


def test_exact_fields_and_original_input_and_other_market_unchanged(tmp_raw_root):
    original = pd.DataFrame([row(), row(code="m1709-C-2000.DCE", exchange="DCE")])
    before = original.copy(deep=True)
    history = setup_history(tmp_raw_root, [row(settle=12, vol=5, oi=7, amount=Decimal("0.55"))])
    corrected, reports, diff = history.reconcile(original, {"20170822"})
    pd.testing.assert_frame_equal(original, before)
    pd.testing.assert_series_equal(corrected.iloc[1], before.iloc[1])
    assert corrected.iloc[0]["vol"] == 5 and corrected.iloc[0]["amount"] == Decimal("0.55")
    assert all(corrected.iloc[0][k] == before.iloc[0][k] for k in ASSERT_FIELDS)
    assert reports[0]["changes"] == {"settle": 1, "vol": 1, "oi": 1, "amount": 1}
    assert Decimal(reports[0]["daily_totals"]["vol"]["before"]) == 2
    assert Decimal(reports[0]["daily_totals"]["vol"]["after"]) == 5
    assert diff.height == 4


@pytest.mark.parametrize("kind", ["missing", "extra"])
def test_contract_set_difference_stops(tmp_raw_root, kind):
    history = setup_history(tmp_raw_root, [row(), row(code="SR801C6300.ZCE")])
    raw = pd.DataFrame(
        [row()]
        if kind == "missing"
        else [row(), row(code="SR801C6300.ZCE"), row(code="SR801C6400.ZCE")]
    )
    with pytest.raises(ValueError, match="contract sets differ"):
        history.reconcile(raw)


@pytest.mark.parametrize("field", ASSERT_FIELDS)
def test_price_assertion_stops(tmp_raw_root, field):
    history = setup_history(tmp_raw_root, [row(**{field: 13})])
    with pytest.raises(ValueError, match="price assertion failed"):
        history.reconcile(pd.DataFrame([row()]))


@pytest.mark.parametrize("day", ["20170820", "20170822"])
def test_ohl_exception_not_reused_on_neighbor_day(tmp_raw_root, day):
    history = setup_history(tmp_raw_root, [row(day, open=15)])
    with pytest.raises(ValueError, match="price assertion failed"):
        history.reconcile(pd.DataFrame([row(day)]))


def test_20170821_ohl_only_override_close_stays_strict(tmp_raw_root):
    history = setup_history(tmp_raw_root, [row("20170821", open=15, high=16, low=8)])
    out, reports, diff = history.reconcile(pd.DataFrame([row("20170821")]))
    assert out.iloc[0]["open"] == 15 and out.iloc[0]["high"] == 16 and out.iloc[0]["low"] == 8
    assert out.iloc[0]["close"] == 11
    assert reports[0]["changes"]["open"] == 1
    assert set(diff["field"]) == {"open", "high", "low"}
    with pytest.raises(ValueError, match="field=close"):
        history.reconcile(pd.DataFrame([row("20170821", close=10)]))


def test_missing_official_trading_day_stops(tmp_raw_root):
    history = setup_history(tmp_raw_root, [row("20170821")])
    with pytest.raises(ValueError, match="Missing CZCE official trading day"):
        history.reconcile(pd.DataFrame([row()]), {"20170822"})


def test_missing_tushare_day_stops(tmp_raw_root):
    history = setup_history(tmp_raw_root, [row()])
    with pytest.raises(ValueError, match="missing/unexpected trading days"):
        history.reconcile(pd.DataFrame([row()]), {"20170822", "20170823"})


def test_2026_unverified_no_overlay_and_no_official_year_required(tmp_raw_root):
    history = setup_history(tmp_raw_root, [row()])
    raw = pd.DataFrame([row("20260105")])
    out, report, diff = history.reconcile(raw)
    pd.testing.assert_frame_equal(raw, out)
    assert report[0]["status"] == "未经官方年度文件核对" and report[0]["overridden_rows"] == 0
    assert diff.is_empty()


def test_manifest_and_official_parquet_tamper_fail(tmp_raw_root):
    history = setup_history(tmp_raw_root, [row()])
    p = history.root / "2017.parquet"
    p.write_bytes(b"broken")
    with pytest.raises(ValueError, match="Changed CZCE official file"):
        history.reconcile(pd.DataFrame([row()]))
    with pytest.raises(ValueError, match="manifest"):
        OfficialOptionHistory(tmp_raw_root, "0" * 64)


def test_null_price_equality_and_nonmatching_null_fail(tmp_raw_root):
    history = setup_history(tmp_raw_root, [row(open=None)])
    out, _, _ = history.reconcile(pd.DataFrame([row(open=None)]))
    assert pd.isna(out.iloc[0]["open"])
    with pytest.raises(ValueError, match="field=open"):
        history.reconcile(pd.DataFrame([row(open=1)]))


def test_structured_notice_gate_is_exact(tmp_raw_root):
    from gr_data.raw.czce.options import NOTICE, parse_official_notice

    history = setup_history(tmp_raw_root, [row()])
    _, reports, _ = history.reconcile(pd.DataFrame([row()]))
    d = reports[0]
    sha = history.manifest_sha256
    assert parse_official_notice(NOTICE + json.dumps(d), sha)
    for key, value in [
        ("exchange", "DCE"),
        ("trade_date", "20170823"),
        ("manifest_sha256", "0" * 64),
        ("rows", True),
        ("overridden_rows", 0),
        ("status", "unknown"),
    ]:
        modified = {**d, key: value}
        if key == "trade_date":
            modified["changes"] = {**d["changes"], "open": 1}
        assert parse_official_notice(NOTICE + json.dumps(modified), sha) is None
    assert parse_official_notice(NOTICE + "not JSON", sha) is None
