"""Tushare 真实接口用例（需 TUSHARE_TOKEN，默认 skip）。

分两类：
- 契约核对：每个接口取 5 行，断言字段齐全。用于发现**供应商 schema 漂移**——
  这类变化不会报错，只会让下游字段悄悄变空。
- 端到端：真实取数 → parquet → 入库真实 PG，断言单位换算与行数。

见 reference/design/tushare/tushare_integration_plan.md §10。
"""

from __future__ import annotations

import os

import pytest
from gr_data.raw.tushare.client import TushareProClient
from gr_data.raw.tushare.fetchers import market, reference


pytestmark = pytest.mark.live_sdk

TOKEN = os.environ.get("TUSHARE_TOKEN", "")
_needs_token = pytest.mark.skipif(not TOKEN, reason="未设置 TUSHARE_TOKEN，跳过真实接口用例")

DAY = {"start_date": "20240102", "end_date": "20240102"}

CONTRACTS = [
    (
        "stock_basic",
        {"list_status": "L"},
        reference.STOCK_BASIC_FIELDS,
        {"ts_code", "name", "list_status", "list_date", "delist_date"},
    ),
    (
        "index_basic",
        {"market": "SSE"},
        reference.INDEX_BASIC_FIELDS,
        {"ts_code", "name", "list_date", "exp_date"},
    ),
    (
        "fut_basic",
        {"exchange": "SHFE", "fut_type": "1"},
        reference.FUT_BASIC_FIELDS,
        {"ts_code", "name", "list_date", "delist_date"},
    ),
    ("trade_cal", {"exchange": "SSE", **DAY}, reference.TRADE_CAL_FIELDS, {"cal_date", "is_open"}),
    (
        "daily",
        DAY,
        market.DAILY_FIELDS,
        {"ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "vol", "amount"},
    ),
    ("adj_factor", DAY, market.ADJ_FACTOR_FIELDS, {"ts_code", "trade_date", "adj_factor"}),
    ("stk_limit", DAY, market.STK_LIMIT_FIELDS, {"ts_code", "trade_date", "up_limit", "down_limit"}),
    ("suspend_d", DAY, market.SUSPEND_FIELDS, {"ts_code", "trade_date", "suspend_type"}),
    (
        "index_daily",
        {"ts_code": "000300.SH", **DAY},
        market.INDEX_DAILY_FIELDS,
        {"ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "vol", "amount"},
    ),
    (
        "fut_daily",
        DAY,
        market.FUT_DAILY_FIELDS,
        {
            "ts_code",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "pre_settle",
            "settle",
            "vol",
            "amount",
            "oi",
        },
    ),
]


@_needs_token
@pytest.mark.parametrize("api,params,fields,required", CONTRACTS, ids=[c[0] for c in CONTRACTS])
def test_api_field_contract(api, params, fields, required):
    """接口返回的字段必须覆盖 ingest 层依赖的全部字段。"""
    df = TushareProClient(token=TOKEN).query(api, limit=5, offset=0, fields=fields, **params)
    missing = required - set(df.columns)
    assert not missing, f"{api} 缺少字段: {sorted(missing)}"


@_needs_token
def test_offset_pagination_is_lossless():
    """offset 翻页必须无重复、无缺口。

    Tushare 超限时**静默截断**（不报错、不返回总数），翻页写错就是静默丢数据。
    用两种页大小翻同一天，结果集必须完全相同。
    """
    c = TushareProClient(token=TOKEN)

    def page(limit: int) -> set[str]:
        out, off = [], 0
        while True:
            p = c.query("daily", limit=limit, offset=off, fields="ts_code,trade_date", **DAY)
            if p.empty:
                break
            out.extend(p["ts_code"].tolist())
            if len(p) < limit:
                break
            off += len(p)
        assert len(out) == len(set(out)), f"页大小 {limit} 出现重复行"
        return set(out)

    big, small = page(6000), page(1000)
    assert big == small
    assert len(big) > 4000  # A 股全市场规模的下限保护
