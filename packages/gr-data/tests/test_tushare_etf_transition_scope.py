"""159908 转型范围的显式单代码例外与原上市日期门禁回归。"""

from __future__ import annotations

import json
from datetime import date
from typing import cast

import pandas as pd
import psycopg
import pytest
from gr_data.common.paths import RawPaths
from gr_data.ingest.base import IngestContext, IngestGateError
from gr_data.ingest.tushare.etf_scope import (
    ETF_TRANSITION_EVIDENCE,
    ETF_TRANSITION_NOTICE,
    exclude_etf_pre_transition,
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
        assert detail["evidence"] == list(ETF_TRANSITION_EVIDENCE)
    pd.testing.assert_frame_equal(rows, before_rows)
    pd.testing.assert_frame_equal(factors, before_factors)
    assert obj._metadata().list_date.tolist() == ["20181210"]


@pytest.mark.parametrize("code", ["159909.SZ", "510680.SH", "512990.SH", "511220.SH"])
def test_other_etf_prelisting_bars_still_stop(tmp_path, code):
    obj, _, _ = make_importer(tmp_path, [(code, "20181207")], {code: "20181210"})
    with pytest.raises(IngestGateError, match="Bar precedes instrument listing"):
        obj.build()
    assert obj.collect_soft_warnings() == []


def test_transition_rule_does_not_hide_later_listing_conflict(tmp_path):
    obj, _, _ = make_importer(tmp_path, [("159908.SZ", "20181210")], {"159908.SZ": "20181211"})
    with pytest.raises(IngestGateError, match="Bar precedes instrument listing"):
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
