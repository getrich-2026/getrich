"""TushareProClient 翻页逻辑测试。

Tushare 单次调用有行数上限且**不会报错、不返回总数**——超限直接截断。
翻页写错就等于静默丢数据，所以这里单独覆盖。
"""

from __future__ import annotations

import pandas as pd
import pytest
from gr_data.raw.tushare.client import PAGE_LIMITS, TushareProClient


class _FakePro:
    """模拟 pro_api 对象：按 offset/limit 切分固定总量。"""

    def __init__(self, total: int):
        self.total = total
        self.calls: list[tuple[int, int]] = []

    def daily(self, limit: int, offset: int, **_):
        self.calls.append((limit, offset))
        rows = [
            {"ts_code": f"c{i}", "trade_date": "20240102"}
            for i in range(offset, min(offset + limit, self.total))
        ]
        return pd.DataFrame(rows)


def _client(total: int) -> tuple[TushareProClient, _FakePro]:
    c = TushareProClient(token="x", sleep_between_requests=0)
    pro = _FakePro(total)
    c._pro = pro  # 绕过真实 SDK 初始化
    return c, pro


def test_query_all_single_page():
    limit = PAGE_LIMITS["daily"]
    c, pro = _client(limit - 1)
    df = c.query_all("daily")
    assert len(df) == limit - 1
    # 未满一页即停，不应有第二次调用
    assert len(pro.calls) == 1


def test_query_all_paginates_until_short_page():
    limit = PAGE_LIMITS["daily"]
    c, pro = _client(limit * 2 + 7)
    df = c.query_all("daily")
    assert len(df) == limit * 2 + 7
    assert [off for _, off in pro.calls] == [0, limit, limit * 2]
    # 行内容不重复、不丢失
    assert df["ts_code"].nunique() == limit * 2 + 7


def test_query_all_exact_multiple_needs_extra_call():
    """整页整除时必须多探一次，否则会漏掉「刚好满页」之后的数据。"""
    limit = PAGE_LIMITS["daily"]
    c, pro = _client(limit)
    df = c.query_all("daily")
    assert len(df) == limit
    assert [off for _, off in pro.calls] == [0, limit]


def test_query_all_empty():
    c, _ = _client(0)
    assert c.query_all("daily").empty


def test_missing_token_raises():
    with pytest.raises(RuntimeError, match="TUSHARE_TOKEN"):
        TushareProClient(token="").query("daily")


def test_query_all_raises_at_offset_cap():
    """超过 offset 上限必须抛错。

    Tushare 在 offset>100000 时返回通用的「查询数据失败」，很容易被当成参数错误；
    而悄悄返回已取到的部分就是静默丢数据。两者都不可接受。
    """
    from gr_data.raw.tushare.client import MAX_OFFSET

    limit = PAGE_LIMITS["daily"]
    c, _ = _client(MAX_OFFSET + limit * 2)
    with pytest.raises(RuntimeError, match="offset 上限"):
        c.query_all("daily", start_date="20240101", end_date="20240131")


def test_query_all_ok_just_below_cap():
    """刚好在上限内不应误报。"""
    from gr_data.raw.tushare.client import MAX_OFFSET

    limit = PAGE_LIMITS["daily"]
    total = MAX_OFFSET - limit  # 末页在 offset<=MAX_OFFSET 处结束
    c, _ = _client(total)
    assert len(c.query_all("daily")) == total


def test_rate_limit_applies_to_pages_and_failed_requests(monkeypatch):
    from gr_data.raw.tushare import client as module

    now = [0.0]
    waits = []

    def sleep(seconds):
        waits.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(module.time, "sleep", sleep)
    client = TushareProClient("x", sleep_between_requests=2)
    client._pro = _FakePro(PAGE_LIMITS["daily"])
    client.query_all("daily")
    assert waits == [2]  # 整页后的空页探测同样消耗配额
    now[0] += 3  # fetcher 已经等待时，客户端不重复等待
    client.query("daily", limit=1, offset=0)
    assert waits == [2]

    def fail(**params):
        raise RuntimeError("temporary failure")

    monkeypatch.setattr(client._pro, "daily", fail)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="temporary failure"):
            client.query("daily")
    assert waits == [2, 2, 2]


def test_offset_limit_is_not_retried(monkeypatch):
    from gr_data.common.retry import PermanentError, retry_call
    from gr_data.raw.tushare import client as module

    monkeypatch.setattr(module, "MAX_OFFSET", 0)
    client, pro = _client(PAGE_LIMITS["daily"])
    with pytest.raises(PermanentError, match="offset 上限"):
        retry_call(client.query_all, "daily", max_retries=3, backoff_base=0)
    assert len(pro.calls) == 1


def test_pipeline_passes_request_interval():
    from gr_data.config.pipeline import Config
    from gr_data.raw import _build_client

    cfg = Config({"providers": {"tushare": {"rate_limit": {"sleep_between_requests_sec": 3}}}})
    assert _build_client("tushare", cfg)._request_interval == 3


@pytest.mark.parametrize("interval", [-1, float("inf"), float("nan")])
def test_invalid_request_interval_rejected(interval):
    with pytest.raises(ValueError, match="finite and nonnegative"):
        TushareProClient(sleep_between_requests=interval)
