"""上市前连续合约占位行的四证据门禁与结构化告警。"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from typing import cast

import pandas as pd
import psycopg
import pytest
from gr_data.common.parquet import write_parquet
from gr_data.ingest.base import IngestContext
from gr_data.ingest.tushare.future_placeholders import (
    ACTIVITY_FIELDS,
    FUTURE_PLACEHOLDER_NOTICE,
    PRICE_FIELDS,
    parse_pre_listing_placeholder_notice,
)
from gr_data.ingest.tushare.importers.market import FutureBars1dImporter


def _row(code="TSL.CFX", day="20180814", **changes):
    return {
        "ts_code": code,
        "trade_date": day,
        **dict.fromkeys(PRICE_FIELDS),
        **dict.fromkeys(ACTIVITY_FIELDS, 0.0),
        **changes,
    }


def _dated(code="TS1812.CFX", day="20180817"):
    return _row(code, day, **dict.fromkeys(PRICE_FIELDS, 99.0))


def _importer(paths, rows, reference=None):
    write_parquet(
        pd.DataFrame(rows), paths.dataset_file("tushare", "fut_daily", "2018-08"), append=False
    )
    if reference:
        write_parquet(
            pd.DataFrame(reference),
            paths.dataset_file("tushare", "fut_daily", "2018-09"),
            append=False,
        )
    imp = FutureBars1dImporter(
        cast(psycopg.Connection, None), IngestContext(paths, months=("2018-08",))
    )
    imp._id_map = lambda: {"TS1812.CFX": 1, "TL2306.CFX": 2}
    return imp


def test_ts_two_pre_listing_rows_classified_without_changing_valid_bar(tmp_raw_root):
    imp = _importer(tmp_raw_root, [_row(), _row("TSL2.CFX"), _dated()])
    frame = imp.build()
    assert len(frame) == 1 and frame.iloc[0]["close"] == 99
    assert frame.iloc[0]["dt"] == date(2018, 8, 17)
    notices = imp.collect_soft_warnings()
    assert len(notices) == 2
    details = [parse_pre_listing_placeholder_notice(w) for w in notices]
    assert all(details)
    assert {d["ts_code"] for d in details if d} == {"TSL.CFX", "TSL2.CFX"}
    assert all(
        d["date"] == "2018-08-14"
        and d["product"] == "TS"
        and d["listing_date"] == "2018-08-17"
        and d["rows"] == 1
        for d in details
        if d
    )
    assert imp.pre_listing_placeholders == details


@pytest.mark.parametrize(
    "changes",
    [
        {"vol": 1},
        {"amount": 1},
        {"oi": 1},
        {"oi": None},
        {"open": float("inf")},
        {"high": -1},
        {"pre_settle": 0},
        {"ts_code": "TS1812.CFX"},
        {"ts_code": "TS.CFX"},
        {"trade_date": "20180817"},
        {"trade_date": "20180820"},
    ],
)
def test_unreviewed_invalid_row_remains_blocking(tmp_raw_root, changes):
    # runner拒绝普通告警；不能只因跳过一行就自动认可。
    imp = _importer(tmp_raw_root, [_dated(), _row(**changes)])
    imp.build()
    warnings = imp.collect_soft_warnings()
    assert any("skipped rows with invalid close and settle: 1" in w for w in warnings)
    assert not imp.pre_listing_placeholders
    assert all(parse_pre_listing_placeholder_notice(w) is None for w in warnings)


def test_no_dated_contract_evidence_does_not_qualify(tmp_raw_root):
    imp = _importer(tmp_raw_root, [_row()])
    assert imp.build().empty
    assert not imp.pre_listing_placeholders
    assert "invalid close and settle" in imp.collect_soft_warnings()[0]


def test_first_contract_must_be_same_product_and_exchange(tmp_raw_root):
    imp = _importer(tmp_raw_root, [_row(), _dated("TF1812.CFX"), _dated("TS1812.SHF")])
    imp._id_map = lambda: {"TF1812.CFX": 1, "TS1812.SHF": 2}
    imp.build()
    assert not imp.pre_listing_placeholders


def test_all_available_raw_months_consulted_and_earliest_date_used(tmp_raw_root):
    imp = _importer(tmp_raw_root, [_row(), _dated()], [_dated("TS1812.CFX", "20180813")])
    imp.build()
    assert not imp.pre_listing_placeholders


def test_product_ending_l_and_later_partition_evidence(tmp_raw_root):
    imp = _importer(tmp_raw_root, [_row("TLL2.CFX"), _dated()], [_dated("TL2306.CFX", "20180903")])
    imp.build()
    assert imp.pre_listing_placeholders[0]["product"] == "TL"
    assert imp.pre_listing_placeholders[0]["listing_date"] == "2018-09-03"


def test_dated_product_ending_l_is_not_a_continuous_code(tmp_raw_root):
    imp = _importer(tmp_raw_root, [_row("TL2306.CFX"), _dated("T1812.CFX")])
    imp._id_map = lambda: {"T1812.CFX": 1}
    imp.build()
    assert not imp.pre_listing_placeholders
    assert "invalid close and settle: 1" in imp.collect_soft_warnings()[0]


def test_mixed_unreviewed_and_placeholder_rows_keep_both_warnings(tmp_raw_root):
    imp = _importer(tmp_raw_root, [_row(), _row("TSL2.CFX", vol=1), _dated()])
    imp.build()
    warnings = imp.collect_soft_warnings()
    assert len(warnings) == 2
    assert parse_pre_listing_placeholder_notice(warnings[0])
    assert parse_pre_listing_placeholder_notice(warnings[1]) is None


def test_notice_parser_rejects_incomplete_or_modified_evidence(tmp_raw_root):
    imp = _importer(tmp_raw_root, [_row(), _dated()])
    imp.build()
    detail = imp.pre_listing_placeholders[0]
    assert parse_pre_listing_placeholder_notice(FUTURE_PLACEHOLDER_NOTICE + json.dumps(detail))
    mutants = []
    for key, value in [
        ("rows", True),
        ("rows", 2),
        ("ts_code", "TS1812.CFX"),
        ("date", "2018-08-17"),
        ("product", "TF"),
        ("listing_date", "2018-08-13"),
        ("dataset", "daily"),
        ("rule", "unknown"),
    ]:
        bad = deepcopy(detail)
        bad[key] = value
        mutants.append(bad)
    for key, value in [("vol", 1), ("oi", None), ("amount", False), ("open", 0)]:
        bad = deepcopy(detail)
        bad["raw_values"][key] = value
        mutants.append(bad)
    for key, value in [
        ("ts_code", "TF1812.CFX"),
        ("ts_code", "TS1813.CFX"),
        ("raw_sha256", "bad"),
        ("date", "2018-08-16"),
        ("raw_partition", "2018-09"),
    ]:
        bad = deepcopy(detail)
        bad["evidence"]["first_dated_contract"][key] = value
        mutants.append(bad)
    bad = deepcopy(detail)
    bad["evidence"]["all_prices_null"] = 1
    mutants.append(bad)
    bad = deepcopy(detail)
    del bad["raw_values"]
    mutants.append(bad)
    for bad in mutants:
        assert (
            parse_pre_listing_placeholder_notice(FUTURE_PLACEHOLDER_NOTICE + json.dumps(bad))
            is None
        )
    assert parse_pre_listing_placeholder_notice(FUTURE_PLACEHOLDER_NOTICE + "null") is None
    assert parse_pre_listing_placeholder_notice(FUTURE_PLACEHOLDER_NOTICE + "not json") is None
    assert (
        parse_pre_listing_placeholder_notice(
            "fut_daily skipped rows with invalid close and settle: 1"
        )
        is None
    )
