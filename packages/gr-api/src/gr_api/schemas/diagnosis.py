"""持仓诊断的请求模型与通用信封。

契约见 ``getrich-design/portfolio-analysis/持仓诊断_表与接口设计.md`` §7.2；
响应模型在 :mod:`gr_api.schemas.diagnosis_response`。本模块只定义形状与结构校验，
代码解析、范围校验和 ``options`` 解析等需要查库的业务校验在 ``services/diagnosis.py``。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Generic, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import TypeVar


T = TypeVar("T")


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


PlanId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]

Intent = Literal[
    "single_portfolio",
    "single_instrument",
    "rebalance_amount",
    "rebalance_holding",
    "multi_portfolio",
]


class ApiResponse(BaseModel, Generic[T]):
    """统一成功响应信封。"""

    code: int
    message: str
    data: T
    timestamp: int
    request_id: str


class HoldingItem(ApiModel):
    """一条持仓。``weight`` 缺省表示「让服务端按等权处理」。"""

    symbol: str = Field(min_length=1, max_length=64)
    # ge=0：一期不支持负权重/空头/杠杆（§8.1 非目标），请求层直接拒绝。
    weight: Decimal | None = Field(default=None, ge=0)


class PortfolioPlan(ApiModel):
    """一个方案。PA-02：最多 100 行原始输入，零权重和重复行也占额度。"""

    plan_id: PlanId
    label: str | None = Field(default=None, max_length=32)
    holdings: list[HoldingItem] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _check_weights(self) -> PortfolioPlan:
        if any(not h.symbol.strip() for h in self.holdings):
            raise ValueError("symbol must not be blank")
        weights = [h.weight for h in self.holdings]
        has_some = any(w is not None for w in weights)
        has_none = any(w is None for w in weights)
        if has_some and has_none:
            # 部分填写时拒绝而不是替用户猜：缺省按 0 与缺省均分剩余会得出完全不同的组合。
            raise ValueError(
                "mixed weight input: all holdings must either all specify weight or all omit it"
            )
        if has_some and sum(w for w in weights if w is not None) <= 0:
            raise ValueError("sum of weights must be > 0")
        return self


class OptionWindow(ApiModel):
    """请求中的统计区间（PA-15 I5）：起止按交易日解析，至少差一天。

    区间是收益观测区间，计算时另取区间前一个交易日的价格，不向区间外扩展凑样本。
    """

    start: date
    end: date

    @model_validator(mode="after")
    def _check_order(self) -> OptionWindow:
        if self.start >= self.end:
            raise ValueError("window start must be before end")
        return self


OptionField = Literal[
    "industry_scheme",
    "benchmark",
    "correlation_window",
    "beta_window",
    "replay_start",
    "stats_window",
]

OptionCode = Annotated[str, Field(min_length=1, max_length=64)]


class CalculationOptions(ApiModel):
    """用户可选计算参数（PA-05、PA-09～PA-12）。

    None 表示：新提交取口径版本默认值；重算时沿用原快照的解析值。
    界面上一个「统计区间」操作同时写入三个区间字段，接口保留三个字段（PA-15 B1）。
    """

    industry_scheme: OptionCode | None = None
    benchmark: OptionCode | None = None  # 标的代码，只接受已验证的全收益基准
    correlation_window: OptionWindow | None = None
    beta_window: OptionWindow | None = None
    replay_start: date | None = None
    stats_window: OptionWindow | None = None


class RecomputeRequest(ApiModel):
    """``POST /snapshots/{id}/recompute``：只覆盖显式给出的字段。"""

    options: CalculationOptions = Field(default_factory=CalculationOptions)
    reset_to_default: list[OptionField] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_reset(self) -> RecomputeRequest:
        given = {k for k, v in self.options.model_dump().items() if v is not None}
        if len(set(self.reset_to_default)) != len(self.reset_to_default):
            raise ValueError("reset_to_default must not repeat fields")
        if given & set(self.reset_to_default):
            raise ValueError("a field cannot be both set and reset")
        return self


class SnapshotRequest(ApiModel):
    """``POST /v1/diagnosis/snapshots`` 的请求体。

    用 ``plans`` 而不是单个 ``holdings``：多方案与后续调仓比较走同一结构，
    编排层按 ``len(plans)`` 与 ``intent`` 决定跑几遍。
    """

    plans: list[PortfolioPlan] = Field(min_length=1, max_length=5)
    intent: Intent | None = None  # 缺省 → 按方案数与解析结果判定
    as_of_date: date | None = None  # 缺省 → 最新已发布数据日期；一期不接受更早日期
    spec_version: str | None = Field(default=None, min_length=1, max_length=32)
    options: CalculationOptions = Field(default_factory=CalculationOptions)

    @model_validator(mode="after")
    def _check_plans(self) -> SnapshotRequest:
        if len({p.plan_id for p in self.plans}) != len(self.plans):
            raise ValueError("plan_id must be unique within a snapshot")
        n = len(self.plans)
        if self.intent in ("single_portfolio", "single_instrument") and n != 1:
            raise ValueError("single intent requires exactly one plan")
        if self.intent in ("rebalance_amount", "rebalance_holding") and n != 2:
            raise ValueError("rebalance intent requires exactly two plans")
        if self.intent == "multi_portfolio" and n < 2:
            raise ValueError("multi_portfolio requires at least two plans")
        return self


class ShareTokenCreated(BaseModel):
    """``POST /snapshots/{id}/share`` 的响应体。"""

    token: str
    expires_at: str


__all__ = [
    "ApiModel",
    "ApiResponse",
    "CalculationOptions",
    "HoldingItem",
    "Intent",
    "OptionField",
    "OptionWindow",
    "PlanId",
    "PortfolioPlan",
    "RecomputeRequest",
    "ShareTokenCreated",
    "SnapshotRequest",
]
