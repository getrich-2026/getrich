"""raw 抓取测试：用 Fake SDK 驱动各 provider fetcher，校验 parquet 落地。"""

from __future__ import annotations

from getrich_data.common.parquet import read_parquet_if_exists
from getrich_data.raw.base import RawContext


def _ctx(tmp_raw_root):
    # 关闭 sleep，加速测试
    return RawContext(paths=tmp_raw_root, rate_limit={"sleep_between_requests_sec": 0,
                                                      "max_retries": 1, "retry_backoff_base_sec": 0})


def test_yinhe_fetch_flow(tmp_raw_root, fake_yinhe):
    from getrich_data.raw.yinhe import REGISTRY

    ctx = _ctx(tmp_raw_root)
    # 顺序：calendar -> hist_code_list -> backward_factor -> kline_day
    REGISTRY["calendar"](fake_yinhe, ctx).fetch("init")
    REGISTRY["hist_code_list"](fake_yinhe, ctx).fetch("init")
    REGISTRY["backward_factor"](fake_yinhe, ctx).fetch("init")
    n = REGISTRY["kline_day"](fake_yinhe, ctx).fetch("init")

    cal = read_parquet_if_exists(tmp_raw_root.dataset_file("yinhe", "calendar", "calendar_SH"))
    assert cal is not None and len(cal) == 3
    codes = read_parquet_if_exists(
        tmp_raw_root.dataset_file("yinhe", "hist_code_list", "EXTRA_STOCK_A_SH_SZ"))
    assert "600000.SH" in set(codes["code"])
    # 日线按 code/月分区
    kday = read_parquet_if_exists(
        tmp_raw_root.code_month_file("yinhe", "kline_day", "600000.SH", "2024-01"))
    assert kday is not None and len(kday) == 2
    assert n > 0


def test_ricequant_fetch_flow(tmp_raw_root, fake_ricequant):
    from getrich_data.raw.ricequant import REGISTRY

    ctx = _ctx(tmp_raw_root)
    REGISTRY["instruments"](fake_ricequant, ctx).fetch("init")
    REGISTRY["calendar"](fake_ricequant, ctx).fetch("init")
    REGISTRY["bars_1d"](fake_ricequant, ctx).fetch("init")

    inst = read_parquet_if_exists(tmp_raw_root.dataset_file("ricequant", "instruments", "stock"))
    assert inst is not None and "order_book_id" in inst.columns
    bar = read_parquet_if_exists(
        tmp_raw_root.dataset_file("ricequant", "bars_1d/stock", "600000.XSHG"))
    assert bar is not None and len(bar) == 2


def test_insight_fetch_flow(tmp_raw_root, fake_insight):
    from getrich_data.raw.insight import REGISTRY

    ctx = _ctx(tmp_raw_root)
    REGISTRY["basic_info"](fake_insight, ctx).fetch("init")
    REGISTRY["trading_days"](fake_insight, ctx).fetch("init")
    REGISTRY["kline_day"](fake_insight, ctx).fetch("init")

    info = read_parquet_if_exists(tmp_raw_root.dataset_file("insight", "basic_info", "StockA"))
    assert info is not None and "htsc_code" in info.columns
    kday = read_parquet_if_exists(
        tmp_raw_root.code_month_file("insight", "kline_day", "600000.SH", "2024-01"))
    assert kday is not None and len(kday) == 2
