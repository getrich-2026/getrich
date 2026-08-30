"""`available_at`：一行数据在系统内**何时可用于计算**。

铁律（AGENTS.md §3.3 + tushare 方案 D11 + datayes PRD §9.0.5）：
下游一律按 ``available_at <= 决策时点`` 过滤，**禁止**用 ``end_date`` /
``trading_day`` / ``ann_date`` 代替。20241231 的年报要到次年 3–4 月才披露，
按 ``end_date`` 对齐等于提前看到三四个月后的信息 —— 而且回测不会报错，
只会把收益算高。

本模块是 `available_at` 的**唯一产地**。散落在各 importer 里各算各的，
迟早会出现「这张表按公告日、那张表按报告期」的静默不一致，而这种不一致
在任何单表测试里都看不出来。

三个函数的可信度依次递减，选用时优先靠上：

1. `from_vendor_timestamp` —— 供应商自带的发布/更新时间戳，逐行精确，
   天然覆盖回算与重述。
2. `from_announce_date` —— 公告日。日期精确到天，具体时刻靠约定。
3. `from_trading_day` —— 交易日 + 文档声明的发布小时。**发布时刻是文档值
   不是实测值**，只在供应商确实没给任何时间戳时才用，且必须在目标表的列
   注释里注明是近似。
"""

from __future__ import annotations

from collections.abc import Callable
from zoneinfo import ZoneInfo

import pandas as pd


CN_TZ = ZoneInfo("Asia/Shanghai")

#: 未落库的降级记录会经由这个签名交给调用方（通常是写 ops.data_quality_check）。
DQRecorder = Callable[[str, dict], None]


class MissingAvailableAtError(ValueError):
    """无法确定可用时点。

    刻意做成硬错误：`available_at` 缺失时唯一"安全"的兜底是把这一行丢掉，
    而任何用业务日期填充的做法都会引入前视偏差。
    """


def _localize(s: pd.Series, hour: int) -> pd.Series:
    """日期序列 → 当日指定小时的 Asia/Shanghai aware 时间戳。

    必须显式钉时区：不带 tzinfo 的时间戳会被当成运行机器的本地时区，
    CI 跑在 UTC 上就整体错 8 小时，而且不报错。
    """
    ts = pd.to_datetime(s, errors="coerce")
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_convert(CN_TZ)
    else:
        ts = ts.dt.tz_localize(CN_TZ)
    return ts + pd.Timedelta(hours=hour)


def from_announce_date(
    ann: pd.Series,
    fallback: pd.Series | None = None,
    *,
    hour: int = 0,
    dq: DQRecorder | None = None,
    dq_rule: str = "available_at_fallback",
) -> pd.Series:
    """公告日 → `available_at`。财报类数据专用。

    ``ann`` 应当是实际公告日（tushare 的 ``f_ann_date``）。它缺失时用
    ``fallback``（通常是 ``ann_date``，可能只是预约披露日）并经 ``dq``
    记一条告警；两者都缺则抛 `MissingAvailableAtError`。

    **绝不用 end_date 兜底** —— 见模块 docstring。
    """
    primary = _localize(ann, hour)
    if fallback is not None:
        alt = _localize(fallback, hour)
        degraded = primary.isna() & alt.notna()
        if degraded.any() and dq is not None:
            dq(dq_rule, {"rows": int(degraded.sum()), "reason": "f_ann_date 缺失，回退 ann_date"})
        primary = primary.where(~degraded, alt)

    if primary.isna().any():
        n = int(primary.isna().sum())
        raise MissingAvailableAtError(f"{n} 行既无实际公告日也无备用公告日，无法确定可用时点")
    return primary


def from_vendor_timestamp(ts: pd.Series, *, default_hour: int) -> pd.Series:
    """供应商自带的发布/更新时间戳 → `available_at`。

    ``default_hour`` 是该时间戳缺失时的退路（取供应商文档声明的发布时点）。
    注意文档声明与实测可能有出入，实测值应写进调用方的注释里，而不是改这里的默认。
    """
    parsed = pd.to_datetime(ts, errors="coerce")
    if getattr(parsed.dt, "tz", None) is not None:
        parsed = parsed.dt.tz_convert(CN_TZ)
    else:
        parsed = parsed.dt.tz_localize(CN_TZ)

    if parsed.isna().any():
        filled = _localize(parsed.dt.normalize(), default_hour)
        parsed = parsed.where(parsed.notna(), filled)
    if parsed.isna().any():
        n = int(parsed.isna().sum())
        raise MissingAvailableAtError(f"{n} 行的供应商时间戳无法解析，且无日期可退回")
    return parsed


def from_trading_day(day: pd.Series, *, publish_hour: int) -> pd.Series:
    """交易日 + 固定发布小时 → `available_at`。日频快照专用。

    例：tushare ``daily_basic`` 官方 15:00–17:00 更新 → ``publish_hour=17``。
    这是三种取法里最弱的一种，取值来自文档而非实测。
    """
    out = _localize(day, publish_hour)
    if out.isna().any():
        n = int(out.isna().sum())
        raise MissingAvailableAtError(f"{n} 行的交易日无法解析，无法确定可用时点")
    return out
