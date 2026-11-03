"""raw 抓取测试：用 Fake SDK 驱动各 provider fetcher，校验 parquet 落地。"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from gr_data.common.parquet import read_parquet_if_exists
from gr_data.ingest.datayes.factors import SW21_FACTORS as DY_SW21_FACTORS
from gr_data.raw.base import RawContext


def _ctx(tmp_raw_root):
    # 关闭 sleep，加速测试
    return RawContext(
        paths=tmp_raw_root,
        rate_limit={"sleep_between_requests_sec": 0, "max_retries": 1, "retry_backoff_base_sec": 0},
    )


def test_yinhe_fetch_flow(tmp_raw_root, fake_yinhe):
    from gr_data.raw.yinhe import REGISTRY

    ctx = _ctx(tmp_raw_root)
    # 顺序：calendar -> hist_code_list -> backward_factor -> kline_day
    REGISTRY["calendar"](fake_yinhe, ctx).fetch("init")
    REGISTRY["hist_code_list"](fake_yinhe, ctx).fetch("init")
    REGISTRY["backward_factor"](fake_yinhe, ctx).fetch("init")
    n = REGISTRY["kline_day"](fake_yinhe, ctx).fetch("init")

    cal = read_parquet_if_exists(tmp_raw_root.dataset_file("yinhe", "calendar", "calendar_SH"))
    assert cal is not None and len(cal) == 3
    codes = read_parquet_if_exists(
        tmp_raw_root.dataset_file("yinhe", "hist_code_list", "EXTRA_STOCK_A_SH_SZ")
    )
    assert "600000.SH" in set(codes["code"])
    # 日线按 code/月分区
    kday = read_parquet_if_exists(
        tmp_raw_root.code_month_file("yinhe", "kline_day", "600000.SH", "2024-01")
    )
    assert kday is not None and len(kday) == 2
    assert n > 0


def test_ricequant_fetch_flow(tmp_raw_root, fake_ricequant):
    from gr_data.raw.ricequant import REGISTRY

    ctx = _ctx(tmp_raw_root)
    REGISTRY["instruments"](fake_ricequant, ctx).fetch("init")
    REGISTRY["calendar"](fake_ricequant, ctx).fetch("init")
    REGISTRY["bars_1d"](fake_ricequant, ctx).fetch("init")

    inst = read_parquet_if_exists(tmp_raw_root.dataset_file("ricequant", "instruments", "stock"))
    assert inst is not None and "order_book_id" in inst.columns
    bar = read_parquet_if_exists(
        tmp_raw_root.dataset_file("ricequant", "bars_1d/stock", "600000.XSHG")
    )
    assert bar is not None and len(bar) == 2


def test_insight_fetch_flow(tmp_raw_root, fake_insight):
    from gr_data.raw.insight import REGISTRY

    ctx = _ctx(tmp_raw_root)
    REGISTRY["basic_info"](fake_insight, ctx).fetch("init")
    REGISTRY["trading_days"](fake_insight, ctx).fetch("init")
    REGISTRY["kline_day"](fake_insight, ctx).fetch("init")

    info = read_parquet_if_exists(tmp_raw_root.dataset_file("insight", "basic_info", "StockA"))
    assert info is not None and "htsc_code" in info.columns
    kday = read_parquet_if_exists(
        tmp_raw_root.code_month_file("insight", "kline_day", "600000.SH", "2024-01")
    )
    assert kday is not None and len(kday) == 2


def test_write_parquet_tmp_name_is_not_a_parquet_partition(tmp_raw_root, monkeypatch):
    """临时文件与目标同目录（os.replace 才原子），且不以 .parquet 结尾，残留时不被 glob 读入。"""
    from gr_data.common import parquet

    seen = []
    real_replace = os.replace

    def spy(src, dst):
        seen.append(Path(src))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    path = tmp_raw_root.code_month_file("yinhe", "kline_day", "600000.SH", "2024-01")
    parquet.write_parquet(pd.DataFrame({"close": [10.0]}), path)

    (tmp,) = seen
    assert tmp.parent == path.parent
    assert tmp.name.startswith("2024-01.parquet.tmp-")
    assert tmp.suffix != ".parquet"
    assert [f.name for f in path.parent.iterdir()] == ["2024-01.parquet"]


def test_write_parquet_failed_replace_keeps_original(tmp_raw_root, monkeypatch):
    """替换失败时原文件不变，临时文件被清理。"""
    from gr_data.common import parquet

    path = tmp_raw_root.code_month_file("yinhe", "kline_day", "600000.SH", "2024-01")
    parquet.write_parquet(pd.DataFrame({"close": [10.0]}), path)

    def fail(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError, match="replace failed"):
        parquet.write_parquet(pd.DataFrame({"close": [99.0]}), path)

    assert pd.read_parquet(path)["close"].tolist() == [10.0]
    assert [f.name for f in path.parent.iterdir()] == ["2024-01.parquet"]


def _write_month_with_stray_tmp(tmp_raw_root, provider, index_name):
    """写一个正式月分区，再造一个 kill 残留的完整临时文件：日期更晚、收盘价是旧值。"""
    from gr_data.common.parquet import write_parquet

    real = tmp_raw_root.code_month_file(provider, "kline_day", "600000.SH", "2024-01")
    idx = pd.DatetimeIndex(["2024-01-02", "2024-01-03"], name=index_name)
    write_parquet(pd.DataFrame({"close": [10.0, 11.0]}, index=idx), real)
    stray_idx = pd.DatetimeIndex(["2024-01-03", "2024-01-31"], name=index_name)
    stray = pd.DataFrame({"close": [99.0, 99.0]}, index=stray_idx)
    write_parquet(stray, real.with_name("2024-01.tmp-deadbeef.parquet"))


@pytest.mark.parametrize(
    ("provider", "index_name"),
    [("yinhe", "kline_time"), ("insight", "time")],
)
def test_kline_day_ignores_stray_tmp_partition(tmp_raw_root, provider, index_name):
    """残留 YYYY-MM.tmp-*.parquet 字典序排在正式分区后，不能在 keep='last' 去重时盖过正式数据。"""
    from gr_data.ingest.insight.adapter import InsightAdapter
    from gr_data.ingest.yinhe.adapter import YinheAdapter

    _write_month_with_stray_tmp(tmp_raw_root, provider, index_name)
    adapter = {"yinhe": YinheAdapter, "insight": InsightAdapter}[provider](tmp_raw_root)

    out = adapter.read_kline_day("600000.SH")

    assert out is not None
    assert out["close"].tolist() == [10.0, 11.0]


@pytest.mark.parametrize("provider", ["yinhe", "insight"])
def test_kline_day_watermark_ignores_stray_tmp_partition(
    tmp_raw_root, fake_yinhe, fake_insight, provider
):
    """水位只看正式月分区；残留临时文件里更晚的日期不能让增量跳过缺口。"""
    from gr_data.raw.insight.fetchers.bars import KlineDayFetcher as InsightKlineDay
    from gr_data.raw.yinhe.fetchers.kline import KlineDayFetcher as YinheKlineDay

    index_name = {"yinhe": "kline_time", "insight": "time"}[provider]
    _write_month_with_stray_tmp(tmp_raw_root, provider, index_name)
    fetcher = (
        YinheKlineDay(fake_yinhe, _ctx(tmp_raw_root))
        if provider == "yinhe"
        else InsightKlineDay(fake_insight, _ctx(tmp_raw_root))
    )

    assert fetcher._local_last_date("600000.SH") == 20240103
    assert fetcher._local_last_date("000001.SZ") is None


def test_yinhe_backward_factor_ignores_stray_tmp_chunk(tmp_raw_root):
    """残留的 <st>_chunk<NNNN>.tmp-*.parquet 也匹配 chunk glob，不能被当成独立 chunk 读入。"""
    from gr_data.common.parquet import write_parquet
    from gr_data.ingest.yinhe.adapter import YinheAdapter

    chunk = tmp_raw_root.dataset_file("yinhe", "backward_factor", "EXTRA_STOCK_A_SH_SZ_chunk0000")
    idx = pd.Index(["2024-01-02"], name="date")
    write_parquet(pd.DataFrame({"600000.SH": [1.5]}, index=idx), chunk)
    stray = pd.DataFrame({"600000.SH": [9.9], "000001.SZ": [9.9]}, index=idx)
    write_parquet(stray, chunk.with_name("EXTRA_STOCK_A_SH_SZ_chunk0000.tmp-deadbeef.parquet"))

    wide = YinheAdapter(tmp_raw_root).read_backward_factor("stock")

    assert wide is not None
    assert wide.columns.tolist() == ["600000.SH"]
    assert wide["600000.SH"].tolist() == [1.5]


def test_tushare_fetch_flow(tmp_raw_root, fake_tushare):
    """Tushare 按月分区抓取：只有有数据的月份落盘，空月份不产生文件。"""
    from gr_data.raw.tushare import REGISTRY
    from gr_data.raw.tushare.context import TushareRawContext

    base = _ctx(tmp_raw_root)
    # start_date 收窄到 2024-01，避免测试遍历十余年的月份；指数须显式白名单
    ctx = TushareRawContext(
        paths=base.paths,
        rate_limit=base.rate_limit,
        start_date=20240101,
        index_codes=("000300.SH",),
    )

    REGISTRY["instruments"](fake_tushare, ctx).fetch("init")
    # 逐日 fetcher 依赖 calendar 提供交易日列表，必须先抓
    REGISTRY["calendar"](fake_tushare, ctx).fetch("init")
    REGISTRY["future_calendar"](fake_tushare, ctx).fetch("init")
    for ds in (
        "daily",
        "daily_basic",
        "adj_factor",
        "stk_limit",
        "suspend_d",
        "index_daily",
        "fut_daily",
    ):
        REGISTRY[ds](fake_tushare, ctx).fetch("init")

    inst = read_parquet_if_exists(tmp_raw_root.dataset_file("tushare", "instruments", "stock"))
    assert inst is not None and set(inst["ts_code"]) == {"600000.SH", "000001.SZ"}
    fut = read_parquet_if_exists(tmp_raw_root.dataset_file("tushare", "instruments", "future"))
    assert fut is not None and "CU2401.SHF" in set(fut["ts_code"])

    cal = read_parquet_if_exists(tmp_raw_root.dataset_file("tushare", "calendar", "SSE"))
    assert cal is not None
    assert set(cal.loc[cal["is_open"].eq(1), "cal_date"]) == {"20240102", "20240103"}
    assert cal.loc[cal["cal_date"].eq("20240101"), "is_open"].tolist() == [0]

    # 逐日数据集按 YYYY-MM 分区
    daily = read_parquet_if_exists(tmp_raw_root.dataset_file("tushare", "daily", "2024-01"))
    assert daily is not None and len(daily) == 4  # 2 codes x 2 days
    # Fake 只在 2024-01 有数据，后续月份不应留下空文件
    months = sorted(p.stem for p in tmp_raw_root.dataset_dir("tushare", "daily").glob("*.parquet"))
    assert months == ["2024-01"]

    # daily_basic 走同一套 _DailyFetcher 模板，字段必须原样落盘（raw 层不归一化）
    basic = read_parquet_if_exists(tmp_raw_root.dataset_file("tushare", "daily_basic", "2024-01"))
    assert basic is not None and len(basic) == 4
    assert {"total_mv", "circ_mv", "pb", "pe_ttm", "total_share"} <= set(basic.columns)
    assert basic["total_mv"].iloc[0] == 12000.0  # 万元，raw 层不换算


def test_tushare_update_refetches_newest_month(tmp_raw_root, fake_tushare):
    """update 模式必须重抓最新的已有月份——当月数据还在增长，已落盘的一定不完整。"""
    from gr_data.raw.tushare import REGISTRY

    ctx = _ctx(tmp_raw_root)
    ctx.start_date = 20240101
    REGISTRY["calendar"](fake_tushare, ctx).fetch("init")
    fetcher = REGISTRY["daily"](fake_tushare, ctx)

    months = [ym for ym, _, _ in fetcher._months_to_fetch("init")]
    assert months[0] == "2024-01" and len(months) > 1

    fetcher.fetch("init")
    # 落盘后只剩 2024-01 一个文件，它同时是「最新已有月份」，应被重抓
    again = [ym for ym, _, _ in fetcher._months_to_fetch("update")]
    assert "2024-01" in again


def test_tushare_bars_require_calendar(tmp_raw_root, fake_tushare):
    """没有交易日历时必须明确报错，而不是对着非交易日空转请求。"""
    import pytest
    from gr_data.raw.tushare import REGISTRY

    ctx = _ctx(tmp_raw_root)
    ctx.start_date = 20240101
    with pytest.raises(RuntimeError, match="缺少交易日历"):
        REGISTRY["daily"](fake_tushare, ctx).fetch("init")


def test_tushare_fetches_by_trade_date_not_range(tmp_raw_root, fake_tushare):
    """逐日接口必须按 trade_date 调用。

    Tushare 的 offset 上限是 100000，全市场一个月约 11.7 万行——
    用日期区间取数会取不全（实测在第 18 页失败）。
    """
    from gr_data.raw.tushare import REGISTRY

    ctx = _ctx(tmp_raw_root)
    ctx.start_date = 20240101
    REGISTRY["calendar"](fake_tushare, ctx).fetch("init")

    seen: list[dict] = []
    orig = fake_tushare.query_all
    fake_tushare.query_all = lambda api, **p: (seen.append({"api": api, **p}), orig(api, **p))[1]
    REGISTRY["daily"](fake_tushare, ctx).fetch("init")

    daily_calls = [c for c in seen if c["api"] == "daily"]
    assert daily_calls, "未发出 daily 请求"
    for c in daily_calls:
        assert "trade_date" in c, f"daily 应按 trade_date 调用，实际: {c}"
        assert "start_date" not in c and "end_date" not in c


def test_tushare_suspend_d_requests_official_fields(tmp_raw_root, fake_tushare):
    """suspend_d 只请求官方输出字段（doc_id=214）。

    `suspend_timing` 区分日内与全天停牌，漏抓则历史无法补回；官方没有
    `suspend_reason` 字段，不能请求。
    """
    from gr_data.raw.tushare import REGISTRY

    ctx = _ctx(tmp_raw_root)
    ctx.start_date = 20240101
    REGISTRY["calendar"](fake_tushare, ctx).fetch("init")

    seen: list[dict] = []
    orig = fake_tushare.query_all
    fake_tushare.query_all = lambda api, **p: (seen.append({"api": api, **p}), orig(api, **p))[1]
    REGISTRY["suspend_d"](fake_tushare, ctx).fetch("init")

    calls = [c for c in seen if c["api"] == "suspend_d"]
    assert calls, "未发出 suspend_d 请求"
    for c in calls:
        assert set(c["fields"].split(",")) == {
            "ts_code",
            "trade_date",
            "suspend_timing",
            "suspend_type",
        }
    path = tmp_raw_root.dataset_file("tushare", "suspend_d", "2024-01")
    assert "suspend_timing" in pd.read_parquet(path).columns


def test_tushare_partial_month_preserves_other_days(tmp_raw_root, fake_tushare, monkeypatch):
    from gr_data.raw.tushare import REGISTRY
    from gr_data.raw.tushare.fetchers import market

    monkeypatch.setattr(market, "today_int", lambda: 20240103)
    ctx = _ctx(tmp_raw_root)
    ctx.start_date = 20240101
    REGISTRY["calendar"](fake_tushare, ctx).fetch("init")
    REGISTRY["daily"](fake_tushare, ctx).fetch("init")
    path = tmp_raw_root.dataset_file("tushare", "daily", "2024-01")
    before = pd.read_parquet(path)
    original = fake_tushare.query_all

    def revised(api_name, **params):
        frame = original(api_name, **params)
        frame["close"] = 12.0
        return frame

    monkeypatch.setattr(fake_tushare, "query_all", revised)
    ctx.start_date = 20240103
    REGISTRY["daily"](fake_tushare, ctx).fetch("update")
    after = pd.read_parquet(path)
    assert len(after) == len(before)
    assert after.loc[after.trade_date.eq("20240102"), "close"].eq(10.5).all()
    assert after.loc[after.trade_date.eq("20240103"), "close"].eq(12).all()


@pytest.mark.parametrize("old_integer", [True, False])
def test_tushare_partial_month_accepts_date_type_change(
    tmp_raw_root, fake_tushare, monkeypatch, old_integer
):
    from gr_data.common.parquet import write_parquet
    from gr_data.raw.tushare import REGISTRY
    from gr_data.raw.tushare.fetchers import market

    monkeypatch.setattr(market, "today_int", lambda: 20240103)
    ctx = _ctx(tmp_raw_root)
    ctx.start_date = 20240101
    REGISTRY["calendar"](fake_tushare, ctx).fetch("init")
    path = tmp_raw_root.dataset_file("tushare", "daily", "2024-01")
    old = fake_tushare.query_all("daily", trade_date="20240102")
    old["trade_date"] = old["trade_date"].astype(int if old_integer else str)
    write_parquet(old, path)
    original = fake_tushare.query_all

    def revised(api_name, **params):
        frame = original(api_name, **params)
        frame["trade_date"] = frame["trade_date"].astype(str if old_integer else int)
        frame["close"] = 12.0
        return frame

    monkeypatch.setattr(fake_tushare, "query_all", revised)
    ctx.start_date = 20240103
    fetcher = REGISTRY["daily"](fake_tushare, ctx)
    for _ in range(2):
        assert fetcher.fetch("update") == 1
        after = pd.read_parquet(path)
        assert len(after) == 4
        assert set(after.trade_date) == {"20240102", "20240103"}
        assert after.loc[after.trade_date.eq("20240102"), "close"].eq(10.5).all()
        assert after.loc[after.trade_date.eq("20240103"), "close"].eq(12).all()
        assert not after.duplicated(["ts_code", "trade_date"]).any()
        assert after["vol"].eq(1000).all()  # raw 单位不变


@pytest.mark.parametrize(
    ("mode", "start", "today", "recover"),
    [
        ("init", 20240101, 20240131, True),
        ("init", 20240103, 20240131, False),
        ("init", 20240101, 20240103, False),
        ("update", 20240101, 20240131, False),
    ],
)
def test_tushare_corrupt_partition_requires_full_month_init(
    tmp_raw_root, fake_tushare, monkeypatch, mode, start, today, recover
):
    from gr_data.raw.tushare import REGISTRY
    from gr_data.raw.tushare.fetchers import market
    from pyarrow import ArrowInvalid

    monkeypatch.setattr(market, "today_int", lambda: today)
    ctx = _ctx(tmp_raw_root)
    ctx.start_date = start
    REGISTRY["calendar"](fake_tushare, ctx).fetch("init")
    path = tmp_raw_root.dataset_file("tushare", "daily", "2024-01")
    path.parent.mkdir(parents=True)
    broken = b"broken parquet partition"
    path.write_bytes(broken)
    fetcher = REGISTRY["daily"](fake_tushare, ctx)
    if recover:
        assert fetcher.fetch(mode) == 1
        after = pd.read_parquet(path)
        assert len(after) == 4
        assert set(after.trade_date) == {"20240102", "20240103"}
    else:
        with pytest.raises(ArrowInvalid):
            fetcher.fetch(mode)
        assert path.read_bytes() == broken


@pytest.mark.parametrize("empty_response", [True, False])
def test_tushare_corrupt_partition_not_replaced_by_incomplete_rebuild(
    tmp_raw_root, fake_tushare, monkeypatch, empty_response
):
    from gr_data.raw.tushare import REGISTRY
    from gr_data.raw.tushare.fetchers import market

    monkeypatch.setattr(market, "today_int", lambda: 20240131)
    ctx = _ctx(tmp_raw_root)
    ctx.start_date = 20240101
    REGISTRY["calendar"](fake_tushare, ctx).fetch("init")
    path = tmp_raw_root.dataset_file("tushare", "daily", "2024-01")
    path.parent.mkdir(parents=True)
    broken = b"broken parquet partition"
    path.write_bytes(broken)
    original = fake_tushare.query_all

    def incomplete(api_name, **params):
        if params["trade_date"] == "20240103":
            if empty_response:
                return pd.DataFrame()
            raise RuntimeError("request failed")
        return original(api_name, **params)

    monkeypatch.setattr(fake_tushare, "query_all", incomplete)
    with pytest.raises((ValueError, RuntimeError)):
        REGISTRY["daily"](fake_tushare, ctx).fetch("init")
    assert path.read_bytes() == broken


def test_tushare_empty_refresh_removes_stale_suspensions(tmp_raw_root, fake_tushare, monkeypatch):
    from gr_data.raw.tushare import REGISTRY
    from gr_data.raw.tushare.fetchers import market
    from gr_data.raw.tushare.suspension_store import read_coverage

    monkeypatch.setattr(market, "today_int", lambda: 20240103)
    ctx = _ctx(tmp_raw_root)
    ctx.start_date = 20240101
    REGISTRY["calendar"](fake_tushare, ctx).fetch("init")
    fetcher = REGISTRY["suspend_d"](fake_tushare, ctx)
    fetcher.fetch("init")
    path = tmp_raw_root.dataset_file("tushare", "suspend_d", "2024-01")
    assert not pd.read_parquet(path).empty
    monkeypatch.setattr(fake_tushare, "query_all", lambda *a, **k: pd.DataFrame())
    assert fetcher.fetch("update") == 1
    assert pd.read_parquet(path).empty
    assert "suspend_type" in pd.read_parquet(path).columns
    assert read_coverage(path)[0] == [date(2024, 1, 2), date(2024, 1, 3)]


def test_tushare_update_ignores_stray_tmp_partition(tmp_raw_root, fake_tushare, monkeypatch):
    """残留 YYYY-MM.tmp-* 不能被当成最新月，否则真正的最新月不再重抓。"""
    from gr_data.common.parquet import write_parquet
    from gr_data.raw.tushare import REGISTRY
    from gr_data.raw.tushare.fetchers import market

    monkeypatch.setattr(market, "today_int", lambda: 20240102)
    ctx = _ctx(tmp_raw_root)
    ctx.start_date = 20240101
    REGISTRY["calendar"](fake_tushare, ctx).fetch("init")
    fetcher = REGISTRY["daily"](fake_tushare, ctx)
    fetcher.fetch("init")
    path = tmp_raw_root.dataset_file("tushare", "daily", "2024-01")
    write_parquet(pd.read_parquet(path), path.with_name("2024-01.tmp-deadbeef.parquet"))

    monkeypatch.setattr(market, "today_int", lambda: 20240103)
    assert fetcher.fetch("update") == 1
    assert sorted(pd.read_parquet(path)["trade_date"].unique()) == ["20240102", "20240103"]


def test_tushare_invalid_coverage_rebuilds_month(tmp_raw_root, fake_tushare, monkeypatch):
    """分区已替换、凭据未写就中断：下次 update 自动整月重建，不需手工删凭据。"""
    from gr_data.common.parquet import write_parquet
    from gr_data.raw.tushare import REGISTRY
    from gr_data.raw.tushare.fetchers import market
    from gr_data.raw.tushare.suspension_store import InvalidCoverageError, read_coverage

    monkeypatch.setattr(market, "today_int", lambda: 20240102)
    ctx = _ctx(tmp_raw_root)
    ctx.start_date = 20240101
    REGISTRY["calendar"](fake_tushare, ctx).fetch("init")
    fetcher = REGISTRY["suspend_d"](fake_tushare, ctx)
    fetcher.fetch("init")
    path = tmp_raw_root.dataset_file("tushare", "suspend_d", "2024-01")
    # 模拟中断：Parquet 已换成新内容，凭据仍是旧哈希。
    write_parquet(pd.read_parquet(path).iloc[0:0], path)
    with pytest.raises(InvalidCoverageError):
        read_coverage(path)

    monkeypatch.setattr(market, "today_int", lambda: 20240103)
    assert fetcher.fetch("update") == 1
    assert read_coverage(path)[0] == [date(2024, 1, 2), date(2024, 1, 3)]
    assert not pd.read_parquet(path).empty


@pytest.mark.parametrize("dataset", ["daily", "suspend_d"])
def test_tushare_failed_refresh_keeps_partition(tmp_raw_root, fake_tushare, monkeypatch, dataset):
    import pytest
    from gr_data.raw.tushare import REGISTRY
    from gr_data.raw.tushare.fetchers import market

    monkeypatch.setattr(market, "today_int", lambda: 20240103)
    ctx = _ctx(tmp_raw_root)
    ctx.start_date = 20240101
    REGISTRY["calendar"](fake_tushare, ctx).fetch("init")
    fetcher = REGISTRY[dataset](fake_tushare, ctx)
    fetcher.fetch("init")
    path = tmp_raw_root.dataset_file("tushare", dataset, "2024-01")
    before = path.read_bytes()
    manifest = path.with_suffix(".coverage.json")
    proof = manifest.read_bytes() if manifest.exists() else None
    original = fake_tushare.query_all

    def fail_second_day(api_name, **params):
        if params.get("trade_date") == "20240103":
            raise RuntimeError("request failed")
        return original(api_name, **params)

    monkeypatch.setattr(fake_tushare, "query_all", fail_second_day)
    with pytest.raises(RuntimeError, match="request failed"):
        fetcher.fetch("update")
    assert path.read_bytes() == before
    if proof is not None:
        assert manifest.read_bytes() == proof


def test_tushare_calendar_leap_day(tmp_raw_root, fake_tushare, monkeypatch):
    from gr_data.raw.tushare.fetchers import reference

    monkeypatch.setattr(reference, "today_int", lambda: 20240229)
    calls = []
    original = fake_tushare.query_all

    def record(api_name, **params):
        calls.append(params)
        return original(api_name, **params)

    monkeypatch.setattr(fake_tushare, "query_all", record)
    reference.CalendarFetcher(fake_tushare, _ctx(tmp_raw_root)).fetch()
    assert [p["end_date"] for p in calls] == ["20250228", "20250228"]


def test_tushare_empty_daily_cannot_erase_existing_bars(tmp_raw_root, fake_tushare, monkeypatch):
    import pytest
    from gr_data.raw.tushare import REGISTRY
    from gr_data.raw.tushare.fetchers import market

    monkeypatch.setattr(market, "today_int", lambda: 20240103)
    ctx = _ctx(tmp_raw_root)
    ctx.start_date = 20240101
    REGISTRY["calendar"](fake_tushare, ctx).fetch("init")
    fetcher = REGISTRY["daily"](fake_tushare, ctx)
    fetcher.fetch("init")
    path = tmp_raw_root.dataset_file("tushare", "daily", "2024-01")
    before = path.read_bytes()
    monkeypatch.setattr(fake_tushare, "query_all", lambda *a, **k: pd.DataFrame())
    with pytest.raises(ValueError, match="Unexplained empty"):
        fetcher.fetch("update")
    assert path.read_bytes() == before


def test_datayes_fetch_flow(tmp_raw_root, fake_datayes):
    """DataYes 五表按自然月落盘，raw 层保留供应商列名与列序。"""
    from gr_data.raw.datayes import REGISTRY

    ctx = _ctx(tmp_raw_root)
    ctx.start_date = 20240101

    for ds in REGISTRY:
        REGISTRY[ds](fake_datayes, ctx).fetch("init")

    exposure = read_parquet_if_exists(
        tmp_raw_root.dataset_file("datayes", "exposure_cne6_sw21", "2024-01")
    )
    assert exposure is not None
    assert len(exposure) == 4  # 2 标的 x 2 天
    assert {"secID", "tradeDate", "updateTime"} <= set(exposure.columns)

    cov = read_parquet_if_exists(
        tmp_raw_root.dataset_file("datayes", "factor_cov_cne6_sw21", "2024-01")
    )
    assert cov is not None
    assert {"factorName", "factorID"} <= set(cov.columns)

    # raw 层不归一化：exposure 与 covariance 的因子列序必须**保持不同**，
    # 这正是 ingest 层要靠 reindex_wide 处理的那个差异
    fac_exp = [c for c in exposure.columns if c.upper() in {f.upper() for f in DY_SW21_FACTORS}]
    fac_cov = [c for c in cov.columns if c.upper() in {f.upper() for f in DY_SW21_FACTORS}]
    assert {c.upper() for c in fac_exp} == {c.upper() for c in fac_cov}
    assert [c.upper() for c in fac_exp] != [c.upper() for c in fac_cov]

    srisk = read_parquet_if_exists(
        tmp_raw_root.dataset_file("datayes", "srisk_cne6_sw21", "2024-01")
    )
    assert srisk is not None and srisk["SRISK"].iloc[0] == 29.6  # raw 层不平方
