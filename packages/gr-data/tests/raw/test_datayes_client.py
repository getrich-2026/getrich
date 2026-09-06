"""DataYes HTTP client 的请求构造与 retCode 分级（不打网络）。

最重要的一组是「区间怎么表达」：五张表里四张不接受纯 `beginDate`/`endDate`，
必须给 `tradeDate` 多值。这条是 live 用例打真接口才发现的（retCode=-2），
接口文档的「是否必须」一栏填的是「多选多」，看不出来。
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from gr_data.raw.datayes.client import (
    DatayesHttpClient,
    DatayesParamError,
    DatayesQueryTooLargeError,
    NotAuthorizedError,
    QuotaExhaustedError,
)


class _RecordingClient(DatayesHttpClient):
    """只记录 query() 的入参，不发请求。"""

    def __init__(self, rows_per_day: int = 1):
        super().__init__(token="fake", sleep_between_requests=0)
        self.calls: list[dict] = []
        self._rows_per_day = rows_per_day

    def query(self, api_path: str, **params):  # type: ignore[override]
        self.calls.append(params)
        days = str(params.get("tradeDate", "")).split(",") if params.get("tradeDate") else []
        return pd.DataFrame({"tradeDate": [d for d in days for _ in range(self._rows_per_day)]})


def test_range_is_expressed_as_trade_date_not_begin_date():
    """区间必须落成 `tradeDate` 多值。

    发 beginDate/endDate 会让 exposure / srisk / specific_ret / covariance 四张表
    直接返回 retCode=-2（At least one of [secID,ticker,tradeDate] ...）。
    """
    c = _RecordingClient()

    c.query_range("/x.json", date(2025, 8, 4), date(2025, 8, 8), chunk_days=10)

    assert len(c.calls) == 1
    params = c.calls[0]
    assert "beginDate" not in params and "endDate" not in params
    assert params["tradeDate"] == "20250804,20250805,20250806,20250807,20250808"


def test_weekends_are_not_requested():
    """周末不进 tradeDate：接口对非交易日只返回空，带上它只让 URL 变长。"""
    c = _RecordingClient()

    # 2025-08-08 周五 → 2025-08-11 周一，中间跨一个周末
    c.query_range("/x.json", date(2025, 8, 8), date(2025, 8, 11), chunk_days=10)

    assert c.calls[0]["tradeDate"] == "20250808,20250811"


def test_all_weekend_span_sends_no_request():
    c = _RecordingClient()

    out = c.query_range("/x.json", date(2025, 8, 9), date(2025, 8, 10), chunk_days=10)

    assert c.calls == []
    assert out.empty


def test_chunking_splits_long_range():
    c = _RecordingClient()

    c.query_range("/x.json", date(2025, 8, 1), date(2025, 8, 29), chunk_days=7)

    # 29 个自然日 / 7 天一段 = 5 段，且每段只含工作日
    assert len(c.calls) == 5
    for params in c.calls:
        for day in params["tradeDate"].split(","):
            assert date(int(day[:4]), int(day[4:6]), int(day[6:])).weekday() < 5


def test_too_large_span_is_halved():
    """结果集过大时折半重试，且折半后的两段合起来仍覆盖原区间。"""

    class _TooLargeOnce(_RecordingClient):
        def query(self, api_path: str, **params):
            days = params["tradeDate"].split(",")
            if len(days) > 3:
                raise DatayesQueryTooLargeError("too large")
            return super().query(api_path, **params)

    c = _TooLargeOnce()
    out = c.query_range("/x.json", date(2025, 8, 4), date(2025, 8, 8), chunk_days=10)

    assert len(out) == 5  # 5 个工作日一天不少
    assert sorted(out["tradeDate"]) == [
        "20250804",
        "20250805",
        "20250806",
        "20250807",
        "20250808",
    ]


def test_single_day_still_too_large_raises():
    """切无可切时必须抛出去 —— 静默返回空表会让下游以为这天没数据。"""

    class _AlwaysTooLarge(_RecordingClient):
        def query(self, api_path: str, **params):
            raise DatayesQueryTooLargeError("too large")

    with pytest.raises(DatayesQueryTooLargeError):
        _AlwaysTooLarge().query_range("/x.json", date(2025, 8, 4), date(2025, 8, 4))


# --------------------------------------------------------------------------- #
# retCode 分级
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "code,exc",
    [
        (-2, DatayesParamError),
        (-9, DatayesParamError),
        (-6, QuotaExhaustedError),
        (-11, QuotaExhaustedError),
        (-7, DatayesQueryTooLargeError),
        (403, NotAuthorizedError),
    ],
)
def test_retcode_grading(code, exc):
    c = DatayesHttpClient(token="fake", sleep_between_requests=0)

    with pytest.raises(exc):
        c._unwrap("/x.json", {"retCode": code, "retMsg": "test"}, {})


def test_retcode_minus_one_is_empty_not_error():
    """-1 是「无数据」不是异常：非交易日、区间内没有记录都会走到这里。"""
    c = DatayesHttpClient(token="fake", sleep_between_requests=0)

    assert c._unwrap("/x.json", {"retCode": -1, "retMsg": "no data"}, {}).empty


def test_row_limit_alarm_treats_near_limit_as_too_large():
    """逼近 10 万行就当作超限折半。

    官方没说超限是报错还是静默截断，按最坏情况（静默截断）防御 ——
    截断了却不报错，会让那一段数据无声地少掉一半。
    """
    from gr_data.raw.datayes.client import ROW_LIMIT_ALARM

    c = DatayesHttpClient(token="fake", sleep_between_requests=0)
    body = {"retCode": 1, "data": [{"a": 1}] * ROW_LIMIT_ALARM}

    with pytest.raises(DatayesQueryTooLargeError):
        c._unwrap("/x.json", body, {})


def test_adaptive_slowdown_has_a_ceiling():
    """-16 的乘性降速必须有天花板。

    没有上限的话，一段网络不好的时间就能把 sleep 推到几十秒，而它**不会自己降
    回来** —— 后面几千次请求全按这个间隔走，一次全量抓取从几小时变成几天，
    日志里却只有一行警告。
    """
    from gr_data.raw.datayes.client import MAX_ADAPTIVE_SLEEP

    c = DatayesHttpClient(token="fake", sleep_between_requests=1.0)

    for _ in range(50):
        with pytest.raises(RuntimeError):
            c._unwrap("/x.json", {"retCode": -16, "retMsg": "too frequent"}, {})

    assert c._sleep == MAX_ADAPTIVE_SLEEP


# --------------------------------------------------------------------------- #
# CLI 的 --months 解析（放这里是因为它只服务于 datayes/tushare 的分批入库）
# --------------------------------------------------------------------------- #
def test_parse_months_range_and_list():
    from gr_data.cli import _parse_months

    assert _parse_months(None) is None
    assert _parse_months("2021-11") == ("2021-11",)
    # 闭区间，且必须跨年正确进位
    assert _parse_months("2021-11..2022-02") == ("2021-11", "2021-12", "2022-01", "2022-02")
    # 混用 + 保序去重
    assert _parse_months("2022-01,2021-11..2021-12,2022-01") == (
        "2022-01",
        "2021-11",
        "2021-12",
    )
