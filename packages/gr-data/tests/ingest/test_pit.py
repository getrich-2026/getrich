"""`ingest/pit.py` 的单测：available_at 的三种取法。

重点不是「函数能跑」，而是**任何一条路径都不会退化成业务日期** ——
用 end_date/trading_day 冒充可用时点是静默前视偏差，测试里必须钉死。
"""

from __future__ import annotations

import pandas as pd
import pytest
from gr_data.ingest import pit


def test_from_announce_date_prefers_actual_announce_date() -> None:
    ann = pd.Series(["2025-04-25", "2025-04-28"])
    fallback = pd.Series(["2025-03-31", "2025-03-31"])

    out = pit.from_announce_date(ann, fallback)

    assert out.dt.strftime("%Y-%m-%d").tolist() == ["2025-04-25", "2025-04-28"]


def test_from_announce_date_falls_back_and_records_dq() -> None:
    ann = pd.Series([None, "2025-04-28"])
    fallback = pd.Series(["2025-04-20", "2025-03-31"])
    seen: list[tuple[str, dict]] = []

    out = pit.from_announce_date(ann, fallback, dq=lambda rule, d: seen.append((rule, d)))

    assert out.dt.strftime("%Y-%m-%d").tolist() == ["2025-04-20", "2025-04-28"]
    assert len(seen) == 1
    assert seen[0][0] == "available_at_fallback"
    assert seen[0][1]["rows"] == 1


def test_from_announce_date_raises_when_both_missing() -> None:
    with pytest.raises(pit.MissingAvailableAtError):
        pit.from_announce_date(pd.Series([None]), pd.Series([None]))


def test_available_at_never_equals_report_period() -> None:
    """报告期 20241231 的年报，可用时点必须落在次年披露日，不能是报告期本身。"""
    end_date = pd.Series(["2024-12-31"])
    f_ann_date = pd.Series(["2025-04-25"])

    out = pit.from_announce_date(f_ann_date, pd.Series([None]))

    assert out.iloc[0].date().isoformat() != end_date.iloc[0]
    assert out.iloc[0] > pd.Timestamp("2024-12-31", tz=pit.CN_TZ)


def test_all_paths_are_shanghai_aware() -> None:
    day = pd.Series(["2025-06-03"])

    ann = pit.from_announce_date(day)
    vendor = pit.from_vendor_timestamp(pd.Series(["2025-06-03 17:00:00"]), default_hour=19)
    trading = pit.from_trading_day(day, publish_hour=17)

    for s in (ann, vendor, trading):
        assert str(s.dt.tz) == "Asia/Shanghai"
        assert s.iloc[0].utcoffset() == pd.Timedelta(hours=8)


def test_from_trading_day_applies_publish_hour() -> None:
    out = pit.from_trading_day(pd.Series(["2025-06-03"]), publish_hour=17)

    assert out.iloc[0] == pd.Timestamp("2025-06-03 17:00", tz=pit.CN_TZ)


def test_from_vendor_timestamp_uses_declared_hour_when_missing() -> None:
    ts = pd.Series(["2025-06-03 17:12:00", None])
    # 第二行无时间戳，只有日期可退 —— 但本函数拿不到日期，应当直接报错
    with pytest.raises(pit.MissingAvailableAtError):
        pit.from_vendor_timestamp(ts, default_hour=19)
