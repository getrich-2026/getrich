"""raw 抓取测试：用 Fake SDK 驱动各 provider fetcher，校验 parquet 落地。"""

from __future__ import annotations

from gr_data.common.parquet import read_parquet_if_exists
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


def test_tushare_fetch_flow(tmp_raw_root, fake_tushare):
    """Tushare 按月分区抓取：只有有数据的月份落盘，空月份不产生文件。"""
    from gr_data.raw.tushare import REGISTRY

    ctx = _ctx(tmp_raw_root)
    # start_date 收窄到 2024-01，避免测试遍历十余年的月份
    ctx.start_date = 20240101

    REGISTRY["instruments"](fake_tushare, ctx).fetch("init")
    # 逐日 fetcher 依赖 calendar 提供交易日列表，必须先抓
    REGISTRY["calendar"](fake_tushare, ctx).fetch("init")
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
    assert cal is not None and len(cal) == 3

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
