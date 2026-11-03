"""历史开市日空响应：固定三次重查、日期边界与月度事件。"""

from __future__ import annotations

import logging
from datetime import date
from unittest.mock import Mock

import pandas as pd
import pytest
from gr_data.common import empty_response_retry as retry
from gr_data.common.parquet import write_parquet
from gr_data.raw.tushare.context import TushareRawContext
from gr_data.raw.tushare.fetchers.market import (
    AdjFactorFetcher,
    Bars1dFetcher,
    DailyBasicFetcher,
    FutureBars1dFetcher,
    StockLimitFetcher,
    SuspensionFetcher,
)


DAY = date(2012, 8, 20)
TODAY = date(2012, 8, 21)
LOG = logging.getLogger(__name__)


def invoke(query, *, result=None, day=DAY, is_open=True):
    return retry.retry_empty_historical_response(
        result if result is not None else pd.DataFrame(),
        query,
        is_empty=lambda value: value is None or value.empty,
        day=day,
        today=TODAY,
        calendar_is_open=is_open,
        logger=LOG,
        context={"provider": "tushare", "dataset": "fut_daily", "exchange": "CFFEX"},
    )


def test_second_requery_success_logs_backoff_and_one_recovery(monkeypatch, caplog):
    waits = []
    monkeypatch.setattr(retry, "sleep_s", waits.append)
    result = pd.DataFrame({"value": [7]})
    query = Mock(side_effect=[pd.DataFrame(), result])
    with retry.capture_empty_response_recoveries() as events:
        assert invoke(query) is result
    assert query.call_count == 2
    assert waits == [5, 15]
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 2
    assert events == [
        {
            "provider": "tushare",
            "dataset": "fut_daily",
            "exchange": "CFFEX",
            "date": "2012-08-20",
            "extra_queries": 2,
        }
    ]


def test_three_requeries_empty_stops_and_never_records_success(monkeypatch):
    waits = []
    monkeypatch.setattr(retry, "sleep_s", waits.append)
    query = Mock(return_value=pd.DataFrame())
    with (
        retry.capture_empty_response_recoveries() as events,
        pytest.raises(retry.EmptyHistoricalResponseError),
    ):
        invoke(query)
    assert query.call_count == 3 and waits == [5, 15, 45]
    assert events == []


@pytest.mark.parametrize("day,is_open", [(DAY, False), (TODAY, True), (date(2012, 8, 22), True)])
def test_closed_today_and_future_days_do_not_requery(day, is_open):
    query = Mock()
    original = pd.DataFrame()
    assert invoke(query, result=original, day=day, is_open=is_open) is original
    query.assert_not_called()


def test_query_exception_is_not_disguised_as_empty_or_retried_here():
    query = Mock(side_effect=RuntimeError("network failed"))
    with pytest.raises(RuntimeError, match="network failed"):
        invoke(query)
    assert query.call_count == 1


def test_nonempty_result_does_not_trigger_any_extra_query():
    original = pd.DataFrame({"x": [None]})
    query = Mock()
    assert invoke(query, result=original) is original
    query.assert_not_called()  # 非空坏值仍由原来的数值校验处理，不能当成空表重查。


@pytest.mark.parametrize(
    "cls", [Bars1dFetcher, AdjFactorFetcher, StockLimitFetcher, DailyBasicFetcher]
)
def test_all_four_stock_endpoints_use_same_bounded_requery(tmp_raw_root, cls):
    write_parquet(
        pd.DataFrame([{"exchange": "SSE", "cal_date": "20120820", "is_open": 1}]),
        tmp_raw_root.dataset_file("tushare", "calendar", "SSE"),
    )
    ctx = TushareRawContext(paths=tmp_raw_root, rate_limit={"sleep_between_requests_sec": 0})
    frame = pd.DataFrame({"ts_code": ["600000.SH"], "trade_date": ["20120820"]})
    client = Mock()
    client.query_all.side_effect = [pd.DataFrame(), pd.DataFrame(), frame]
    with retry.capture_empty_response_recoveries() as events:
        assert cls(client, ctx)._fetch_day(DAY) is frame
    assert client.query_all.call_count == 3 and events[0]["extra_queries"] == 2


def test_sparse_suspensions_keep_legal_empty_without_requery(tmp_raw_root):
    client = Mock()
    frame = pd.DataFrame()
    client.query_all.return_value = frame
    ctx = TushareRawContext(paths=tmp_raw_root, rate_limit={"sleep_between_requests_sec": 0})
    assert SuspensionFetcher(client, ctx)._fetch_day(DAY) is frame
    assert client.query_all.call_count == 1


def test_recovered_future_response_still_checks_requested_exchange(tmp_raw_root):
    client = Mock()
    client.query_all.side_effect = [
        pd.DataFrame(),
        pd.DataFrame({"ts_code": ["CU1209.SHF"], "trade_date": ["20120820"]}),
    ]
    ctx = TushareRawContext(paths=tmp_raw_root, rate_limit={"sleep_between_requests_sec": 0})
    obj = FutureBars1dFetcher(client, ctx)
    obj._exchange_days = {"CFFEX": {DAY}}
    with pytest.raises(ValueError, match="unexpected exchange"):
        obj._fetch_day(DAY)
    assert client.query_all.call_count == 2
