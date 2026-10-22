"""D-023 的日级状态：输入须是同一来源、同一交易日的证据，不跨日填充。"""

from __future__ import annotations

import pandas as pd


def resolve_trading_status(evidence: pd.DataFrame) -> pd.Series:
    """由有无行情、采集覆盖及事件标志生成四态。

    Args:
        evidence: 布尔列 has_bar、covered、full_suspend、intraday_suspend、resumed。
            行顺序不影响结果；调用方负责按标的和事件日期关联。

    Returns:
        NORMAL、HALTED、INTRADAY_HALTED 或 UNKNOWN；冲突和缺证据返回 UNKNOWN。
        S/R 同日且没有时段无法确定顺序，不武断以 R 覆盖 S。
        时段存在但没有行情也为未知，不能伪装全天停牌。

    Complexity:
        时间和额外空间均为 O(n)，不展开历史日期或前向填充事件。
    """
    e = evidence.fillna(False).astype(bool)
    result = pd.Series("UNKNOWN", index=e.index, dtype=object)
    normal = e.has_bar & ~e.full_suspend & ~e.intraday_suspend
    intraday = e.has_bar & e.intraday_suspend & ~e.full_suspend
    halted = ~e.has_bar & e.full_suspend & ~e.intraday_suspend & ~e.resumed
    result.loc[e.covered & normal] = "NORMAL"
    result.loc[e.covered & intraday] = "INTRADAY_HALTED"
    result.loc[e.covered & halted] = "HALTED"
    return result


def event_flags(events: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """按指定标的／日期键聚合事件；时段为空的 S 与日内 S 分开。"""
    flags = events[keys].copy()
    suspended = events["suspend_type"].eq("S")
    flags["full_suspend"] = suspended & events["suspend_timing"].isna()
    flags["intraday_suspend"] = suspended & events["suspend_timing"].notna()
    flags["resumed"] = events["suspend_type"].eq("R")
    return flags.groupby(keys, as_index=False).any()
