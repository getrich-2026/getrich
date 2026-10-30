"""DataYes available_at：时间戳缺失才退回文档发布时点，解析失败必须拒绝。"""

from __future__ import annotations

import pandas as pd
import pytest
from gr_data.ingest.datayes.importers.riskmodel import VENDOR_PUBLISH_HOUR, _available_at


def test_missing_update_time_falls_back_to_documented_hour():
    df = pd.DataFrame({"tradeDate": ["2024-01-02"], "updateTime": [None]})

    ts = _available_at(df).iloc[0]

    assert (ts.year, ts.month, ts.day, ts.hour) == (2024, 1, 2, VENDOR_PUBLISH_HOUR)


def test_unparseable_update_time_rejected():
    """退回 17:00 可能早于真实发布时间，格式异常不能静默当作缺失。"""
    df = pd.DataFrame({"tradeDate": ["2024-01-02", "2024-01-02"], "updateTime": [None, "bad"]})

    with pytest.raises(ValueError, match="updateTime 含 1 行无法解析"):
        _available_at(df)
