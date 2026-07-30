"""TushareProClient 翻页逻辑测试。

Tushare 单次调用有行数上限且**不会报错、不返回总数**——超限直接截断。
翻页写错就等于静默丢数据，所以这里单独覆盖。
"""

from __future__ import annotations

import pandas as pd
import pytest

from getrich_data.raw.tushare.client import PAGE_LIMITS, TushareProClient


class _FakePro:
    """模拟 pro_api 对象：按 offset/limit 切分固定总量。"""

    def __init__(self, total: int):
        self.total = total
        self.calls: list[tuple[int, int]] = []

    def daily(self, limit: int, offset: int, **_):
        self.calls.append((limit, offset))
        rows = [{"ts_code": f"c{i}", "trade_date": "20240102"}
                for i in range(offset, min(offset + limit, self.total))]
        return pd.DataFrame(rows)


def _client(total: int) -> tuple[TushareProClient, _FakePro]:
    c = TushareProClient(token="x")
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
