"""四证据、原始行优先和整段采集预检的回归。"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest
from gr_data.common.parquet import write_parquet
from gr_data.ingest.base import IngestContext
from gr_data.ingest.tushare.importers.future_calendar import FutureCalendarImporter
from gr_data.raw.tushare.calendar_rules import (
    FUTURE_CLOSED_DAY_RULE,
    FutureCalendarGapError,
    complete_future_calendar,
)
from gr_data.raw.tushare.context import TushareRawContext
from gr_data.raw.tushare.fetchers.reference import FutureCalendarFetcher


def setup_calendar(paths):
    raw = pd.DataFrame(
        [
            {"exchange": "SHFE", "cal_date": "20240105", "is_open": 1, "pretrade_date": "20240104"},
            {"exchange": "SHFE", "cal_date": "20240108", "is_open": 1, "pretrade_date": "20240105"},
        ]
    )
    sse = pd.DataFrame(
        [
            {"exchange": "SSE", "cal_date": d, "is_open": flag}
            for d, flag in [("20240105", 1), ("20240106", 0), ("20240107", 0), ("20240108", 1)]
        ]
    )
    write_parquet(raw, paths.dataset_file("tushare", "future_calendar", "SHFE"), append=False)
    write_parquet(sse, paths.dataset_file("tushare", "calendar", "SSE"), append=False)
    return raw, sse


def complete(paths):
    return complete_future_calendar(paths, "SHFE", date(2024, 1, 5), date(2024, 1, 8))


def test_all_four_conditions_infer_closed_and_keep_raw(tmp_raw_root):
    original, _ = setup_calendar(tmp_raw_root)
    path = tmp_raw_root.dataset_file("tushare", "future_calendar", "SHFE")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    result = complete(tmp_raw_root)
    assert len(result.frame) == 4
    assert len(result.inferred) == 2
    assert {r["date"] for r in result.inferred} == {"2024-01-06", "2024-01-07"}
    for row in result.inferred:
        assert row["rule"] == FUTURE_CLOSED_DAY_RULE
        assert row["is_open"] is False and row["has_night"] is False
        assert all(v["passed"] for v in row["evidence"].values())
        assert row["evidence"]["no_raw_fut_daily"]["month_partition_present"] is False
        json.dumps(row, allow_nan=False)
    pd.testing.assert_frame_equal(pd.read_parquet(path), original)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize(
    "damage", ["sse_open", "bar", "chain", "sse_day_missing", "sse_file_missing", "no_next_open"]
)
def test_missing_evidence_stops_instead_of_guessing(tmp_raw_root, damage):
    raw, sse = setup_calendar(tmp_raw_root)
    if damage == "sse_open":
        sse.loc[sse.cal_date.eq("20240106"), "is_open"] = 1
    elif damage == "sse_day_missing":
        sse = sse.loc[sse.cal_date.ne("20240106")]
    elif damage == "bar":
        write_parquet(
            pd.DataFrame([{"ts_code": "CU2401.SHF", "trade_date": "20240106", "vol": 0}]),
            tmp_raw_root.dataset_file("tushare", "fut_daily", "2024-01"),
            append=False,
        )
    elif damage == "chain":
        raw.loc[raw.cal_date.eq("20240108"), "pretrade_date"] = "20240104"
    elif damage == "no_next_open":
        raw = raw.iloc[:1]
    write_parquet(
        raw, tmp_raw_root.dataset_file("tushare", "future_calendar", "SHFE"), append=False
    )
    write_parquet(sse, tmp_raw_root.dataset_file("tushare", "calendar", "SSE"), append=False)
    if damage == "sse_file_missing":
        tmp_raw_root.dataset_file("tushare", "calendar", "SSE").unlink()
    with pytest.raises(ValueError):
        complete(tmp_raw_root)


def test_other_exchange_bar_does_not_block_this_exchange(tmp_raw_root):
    setup_calendar(tmp_raw_root)
    write_parquet(
        pd.DataFrame([{"ts_code": "SR2401.ZCE", "trade_date": "20240106"}]),
        tmp_raw_root.dataset_file("tushare", "fut_daily", "2024-01"),
        append=False,
    )
    assert len(complete(tmp_raw_root).inferred) == 2


def test_existing_supplier_rows_win_without_sse_or_bar_overrides(tmp_raw_root):
    original, _ = setup_calendar(tmp_raw_root)
    extra = pd.DataFrame(
        [
            {"exchange": "SHFE", "cal_date": d, "is_open": flag, "pretrade_date": "20240105"}
            for d, flag in [("20240106", 1), ("20240107", 0)]
        ]
    )
    original = pd.concat([original, extra], ignore_index=True)
    write_parquet(
        original, tmp_raw_root.dataset_file("tushare", "future_calendar", "SHFE"), append=False
    )
    tmp_raw_root.dataset_file("tushare", "calendar", "SSE").unlink()
    result = complete(tmp_raw_root)
    pd.testing.assert_frame_equal(result.frame, original)
    assert result.inferred == []


def test_fetch_checks_whole_range_and_reports_all_bad_days(tmp_raw_root):
    raw, sse = setup_calendar(tmp_raw_root)
    sse["is_open"] = 1
    write_parquet(sse, tmp_raw_root.dataset_file("tushare", "calendar", "SSE"), append=False)
    client = MagicMock()
    client.query_all.return_value = raw
    ctx = TushareRawContext(
        paths=tmp_raw_root,
        start_date=20240105,
        end_date=20240108,
        future_exchanges=("SHFE",),
        rate_limit={"sleep_between_requests_sec": 0},
    )
    with pytest.raises(ValueError, match="Unresolved future calendar gaps count=2") as exc:
        FutureCalendarFetcher(client, ctx).fetch()
    assert "2024-01-06" in str(exc.value) and "2024-01-07" in str(exc.value)
    pd.testing.assert_frame_equal(
        pd.read_parquet(tmp_raw_root.dataset_file("tushare", "future_calendar", "SHFE")), raw
    )


def test_importer_writes_only_inferred_days_and_stages_dedup_audit(tmp_raw_root):
    setup_calendar(tmp_raw_root)
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []
    obj = FutureCalendarImporter(
        conn,
        IngestContext(tmp_raw_root),
        first=date(2024, 1, 5),
        last=date(2024, 1, 8),
        exchanges=("SHFE",),
    )
    frame = obj.build()
    assert frame.trading_day.tolist() == [date(2024, 1, 6), date(2024, 1, 7)]
    assert not frame.is_open.any() and not frame.has_night.any()
    assert frame.prev_trading_day.tolist() == [date(2024, 1, 5)] * 2
    assert frame.next_trading_day.tolist() == [date(2024, 1, 8)] * 2
    obj._record_run(2, [])
    pending = cur.executemany.call_args.args[1]
    assert len(pending) == 2
    assert {p[2].obj["date"] for p in pending} == {"2024-01-06", "2024-01-07"}
    # 事务内登记不自行提交；提交权属于BaseImporter，与日历一起原子提交。
    conn.commit.assert_not_called()
    cur.fetchall.return_value = [(p[2].obj["observation_id"],) for p in pending]
    cur.executemany.reset_mock()
    obj._record_run(2, [])
    cur.executemany.assert_not_called()


def test_bad_chain_reports_every_gap_and_all_four_checks(tmp_raw_root):
    raw, _ = setup_calendar(tmp_raw_root)
    raw["pretrade_date"] = "20240104"
    write_parquet(
        raw, tmp_raw_root.dataset_file("tushare", "future_calendar", "SHFE"), append=False
    )
    with pytest.raises(FutureCalendarGapError) as exc:
        complete(tmp_raw_root)
    assert len(exc.value.failures) == 2
    assert all(len(item["evidence"]) == 4 for item in exc.value.failures)
