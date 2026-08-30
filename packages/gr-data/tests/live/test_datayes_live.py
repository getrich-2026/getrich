"""DataYes 真实接口契约用例（需要 DATAYES_TOKEN，默认 skip）。

作用是**发现供应商 schema 漂移**：字段改名、因子集合变更、后缀集合扩大、
量纲被悄悄换掉，这些在 Fake 上永远测不出来，只有打真实接口才会暴露。

跑法：
    DATAYES_TOKEN=... uv run pytest packages/gr-data/tests/live/test_datayes_live.py -v -m live_sdk
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest
from gr_data.ingest.datayes import factors as fx
from gr_data.ingest.datayes.symbols import DATAYES_SUFFIX_TO_EXCHANGE, split_sec_id
from gr_data.raw.datayes.client import DatayesHttpClient


pytestmark = pytest.mark.live_sdk

TOKEN = os.environ.get("DATAYES_TOKEN", "")

#: 五张表的 (dataset, api_path, 必须存在的字段)。加 fetcher 时同步加一行。
CONTRACTS = [
    (
        "exposure",
        "/api/equity/getDy1dExposureCNE6SW21.json",
        {"secID", "ticker", "tradeDate", "updateTime"},
    ),
    ("factor_ret", "/api/equity/getDy1dFactorRetCNE6SW21.json", {"tradeDate", "updateTime"}),
    (
        "covariance",
        "/api/equity/getDy1dCovarianceCNE6SW21.json",
        {"tradeDate", "factorName", "updateTime"},
    ),
    (
        "srisk",
        "/api/equity/getDy1dSriskCNE6SW21.json",
        {"secID", "tradeDate", "SRISK", "updateTime"},
    ),
    (
        "specific_ret",
        "/api/equity/getDy1dSpecificRetCNE6SW21.json",
        {"secID", "tradeDate", "SPRET", "updateTime"},
    ),
]


@pytest.fixture(scope="module")
def client() -> DatayesHttpClient:
    if not TOKEN:
        pytest.skip("未设置 DATAYES_TOKEN")
    c = DatayesHttpClient(token=TOKEN, sleep_between_requests=1.0)
    yield c
    c.close()


@pytest.fixture(scope="module")
def probe_window() -> tuple[date, date]:
    """取最近的一小段区间。不钉死某一天，避免碰上非交易日就整组失败。"""
    end = date.today() - timedelta(days=1)
    return end - timedelta(days=6), end


@pytest.mark.parametrize("name,path,required", CONTRACTS, ids=[c[0] for c in CONTRACTS])
def test_api_field_contract(client, probe_window, name, path, required):
    begin, end = probe_window
    df = client.query_range(path, begin, end, chunk_days=7)

    assert not df.empty, f"{name} 在 {begin}~{end} 无数据"
    missing = required - set(df.columns)
    assert not missing, f"{name} 缺少字段 {missing}"


def test_three_wide_tables_share_the_same_factor_set(client, probe_window):
    """三张宽表的因子集合必须逐字相等 —— 它们要拼进同一个 model_run。

    注意断言的是**集合**：顺序本来就不同，那是设计上已知并由 reindex_wide 处理的。
    """
    begin, end = probe_window
    sets = {}
    for name, path in [
        ("exposure", "/api/equity/getDy1dExposureCNE6SW21.json"),
        ("factor_ret", "/api/equity/getDy1dFactorRetCNE6SW21.json"),
        ("covariance", "/api/equity/getDy1dCovarianceCNE6SW21.json"),
    ]:
        df = client.query_range(path, begin, end, chunk_days=7)
        sets[name] = {fx.canonical(c) for c in df.columns} - {None}

    assert sets["exposure"] == sets["factor_ret"] == sets["covariance"]
    # 本轮区间在申万 2021 体系内，活跃因子应为 52 个
    assert len(sets["exposure"]) == len(fx.ALL_FACTORS)


def test_active_factor_set_matches_sw21(client, probe_window):
    """当日活跃因子集合应等于申万 2021 体系的 52 个。

    不等就说明供应商换了体系（或我们的常量过期了），必须人工确认后开新
    model_version —— 这条失败是**信号，不是噪声**。
    """
    begin, end = probe_window
    df = client.query_range("/api/equity/getDy1dExposureCNE6SW21.json", begin, end, chunk_days=7)

    active = set(fx.active_factors(df))

    assert active == set(fx.SW21_FACTORS), (
        f"多出 {sorted(active - set(fx.SW21_FACTORS))}，"
        f"缺少 {sorted(set(fx.SW21_FACTORS) - active)}"
    )


def test_sec_id_suffixes_are_all_known(client, probe_window):
    """枚举真实返回的 secID 后缀（未决项 U21）。

    出现新后缀就失败 —— 那正是我们想要的信号：说明覆盖范围变了，
    symbols.py 的映射表需要人工确认后扩充，而不是让程序自己猜。
    """
    begin, end = probe_window
    df = client.query_range("/api/equity/getDy1dExposureCNE6SW21.json", begin, end, chunk_days=7)

    suffixes = {split_sec_id(s)[1] for s in df["secID"].astype(str)}

    unknown = suffixes - set(DATAYES_SUFFIX_TO_EXCHANGE)
    assert not unknown, f"出现未登记的 secID 后缀：{sorted(unknown)}"


def test_industry_dummies_and_country(client, probe_window):
    """行业哑变量每行恰有一个 1、COUNTRY 恒为 1。

    这两条同时也是「因子列没有错位」的最强证据。
    """
    import numpy as np

    begin, end = probe_window
    df = client.query_range("/api/equity/getDy1dExposureCNE6SW21.json", begin, end, chunk_days=7)
    order = list(fx.active_factors(df))
    values = fx.reindex_wide(df, order)

    ind_idx = [i for i, f in enumerate(order) if fx.FACTOR_TYPE[f] == "industry"]
    row_sum = np.nan_to_num(values[:, ind_idx], nan=0.0).sum(axis=1)
    assert np.allclose(row_sum, 1.0)

    country = values[:, order.index(fx.MARKET_FACTOR)]
    assert np.allclose(np.nan_to_num(country, nan=0.0), 1.0)


def test_srisk_is_annualized_percent_volatility(client, probe_window):
    """SRISK 的量纲复核：年化百分比波动率，P50 应在 20~45 的量级。

    如果哪天它变成了小数（0.2~0.45）或方差（400~2000），说明供应商改了口径，
    而 `scaling.srisk_is_variance` 与 `srisk_unit` 必须跟着改 ——
    不改的话入库值会差好几个数量级，且不会报错。
    """
    begin, end = probe_window
    df = client.query_range("/api/equity/getDy1dSriskCNE6SW21.json", begin, end, chunk_days=7)

    p50 = float(df["SRISK"].astype(float).median())

    assert 10.0 < p50 < 80.0, f"SRISK 中位数 {p50}，与「年化百分比波动率」的量纲不符"
