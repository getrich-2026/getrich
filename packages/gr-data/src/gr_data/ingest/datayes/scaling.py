"""通联数据的量纲定标配置。

## 为什么没有默认值

同一个模型内部量纲是混着的（实测，见 `providers/datayes.md` §9.0）：

| 数据 | 单位 |
|---|---|
| exposure 风格 | 无量纲 z-score |
| exposure 行业 / COUNTRY | 0/1 哑变量 |
| `factor_ret` | **小数**，日频 |
| `SPRET` | **百分比**，日频 |
| `SRISK` | **年化百分比波动率 σ**（不是方差） |
| `covariance` | **年化 %²** |

于是 $r = 100 X f + u$ —— 少乘那个 100，个股收益就差两个数量级；把 SRISK 当方差用，
特质风险就差一个数量级。两种错误都不会报错。

因此这些系数**必须从配置显式声明，缺任何一个键就拒绝启动**。给默认值等于
「配置漏了就按一套猜的系数算」，正是 AGENTS.md「不得静默改单位」要挡的事。
项目里的原话是：允许不换算，不允许糊里糊涂地换算。

配置项会原样落进 `factor.model_run.units`，让「配置 → 库内 → 下游」三处口径
可以互相对账。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gr_data.common.retry import PermanentError


REQUIRED_KEYS = (
    "mode",
    "exposure_unit",
    "factor_ret_unit",
    "cov_unit",
    "srisk_unit",
    "srisk_is_variance",
    "spret_unit",
    "calibrated",
)


@dataclass(frozen=True)
class Scaling:
    """一份完整的量纲声明。**所有字段都没有默认值**，见模块 docstring。"""

    mode: str  # calibrated | passthrough
    exposure_unit: str  # zscore（风格）/ dummy（行业）
    factor_ret_unit: str  # dec_daily
    cov_unit: str  # pct2_annual
    srisk_unit: str  # pct_annual
    srisk_is_variance: bool  # False → 入库前平方成方差
    spret_unit: str  # pct_daily
    calibrated: bool  # 全区间复核是否通过

    def as_units(self) -> dict[str, Any]:
        """落进 `factor.model_run.units` 的形态。"""
        return {
            "mode": self.mode,
            "exposure": self.exposure_unit,
            "factor_return": self.factor_ret_unit,
            "covariance": self.cov_unit,
            "specific_risk": "pct2_annual" if not self.srisk_is_variance else self.srisk_unit,
            "specific_risk_source": self.srisk_unit,
            "specific_return": self.spret_unit,
        }


def load_scaling(section: dict[str, Any] | None) -> Scaling:
    """从 `providers.datayes.scaling` 构造。缺键即抛 `PermanentError`。

    抛 `PermanentError` 而不是普通异常：这是确定性失败，`retry_call` 退避
    重试几十秒之后仍然缺那个键，只会把真正的原因淹没在重试日志里。
    """
    section = section or {}
    missing = [k for k in REQUIRED_KEYS if k not in section]
    if missing:
        raise PermanentError(
            f"providers.datayes.scaling 缺少必填键：{missing}。"
            "量纲系数不设默认值——缺配置时按猜测换算，错了也不会报错。"
            "取值依据见 getrich-design `data-platform/providers/datayes.md` §9.0。"
        )
    return Scaling(
        mode=str(section["mode"]),
        exposure_unit=str(section["exposure_unit"]),
        factor_ret_unit=str(section["factor_ret_unit"]),
        cov_unit=str(section["cov_unit"]),
        srisk_unit=str(section["srisk_unit"]),
        srisk_is_variance=bool(section["srisk_is_variance"]),
        spret_unit=str(section["spret_unit"]),
        calibrated=bool(section["calibrated"]),
    )
