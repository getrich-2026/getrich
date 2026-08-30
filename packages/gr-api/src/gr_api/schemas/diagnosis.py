"""持仓诊断的请求与响应 Pydantic 模型。

契约见 ``getrich-design/portfolio-analysis/持仓诊断_表与接口设计.md`` §7.2（请求）
与 §7.3（响应）。

本模块只定义**形状**，不含任何计算与 SQL —— 那些在 ``services/diagnosis.py``。

一处贯穿全文的设计：:data:`MetricValue` 是**判别联合**而不是「一个可空的裸类」。
``UnavailableMetric`` 根本没有 ``value`` 字段，于是
``{"status": "ok", "value": null}`` 或 ``{"status": "unavailable", "value": 1.0}``
这类非法组合在类型层面就构造不出来。这把架构篇 §7.1 的「不得静默估算」从**约定**
升级成**类型约束**：前端拿到 unavailable 时无从渲染成数字，只能显示原因。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Generic, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator
from typing_extensions import TypeAliasType, TypeVar


T = TypeVar("T")


# ---------------------------------------------------------------------------
# 枚举与基础类型
# ---------------------------------------------------------------------------


class MetricStatus(StrEnum):
    """指标状态三态。"""

    OK = "ok"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ReasonCode(StrEnum):
    """稳定的机器可读原因码。

    前端的判断逻辑一律基于本枚举；``reason`` 字段只做人类可读展示，
    **不得**用于分支判断（文案随时会改，改了就静默失配）。
    """

    FACTOR_MODEL_UNAVAILABLE = "factor_model_unavailable"  # 缺口 G2
    HISTORY_INSUFFICIENT = "history_insufficient"
    COVERAGE_BELOW_THRESHOLD = "coverage_below_threshold"
    SPEC_NOT_DEFINED = "spec_not_defined"  # 缺口 G6：口径未定
    LOOKTHROUGH_INCOMPLETE = "lookthrough_incomplete"  # 缺口 G4
    BENCHMARK_MISSING = "benchmark_missing"
    NEW_LISTING_SHORT_WINDOW = "new_listing_short_window"


Confidence = Literal["high", "medium", "low"]

Intent = Literal[
    "single_portfolio",
    "single_instrument",
    "rebalance_amount",
    "rebalance_holding",
    "multi_portfolio",
]

ReportMode = Literal["standard", "single_instrument", "compare"]

RunStatus = Literal["pending", "running", "succeeded", "partially_succeeded", "failed"]

WeightMode = Literal["user", "equal"]

UserLevel = Literal["retail", "pro"]


class DateRange(BaseModel):
    """闭区间的起止交易日。"""

    start: date
    end: date


# ---------------------------------------------------------------------------
# MetricValue 判别联合
# ---------------------------------------------------------------------------


class OkMetric(BaseModel, Generic[T]):
    """正常出数。"""

    status: Literal["ok"] = "ok"
    value: T
    method: str  # 实际使用的计算方法，如 'historical' / 'forward'
    window_target: DateRange | None = None
    window_actual: DateRange | None = None
    confidence: Confidence = "high"


class DegradedMetric(BaseModel, Generic[T]):
    """出数了，但口径被降级（如前瞻协方差不可用而退历史口径）。

    ``reason`` 必填：降级而不说明原因，用户看到的就是一个来路不明的数字。
    """

    status: Literal["degraded"] = "degraded"
    value: T
    method: str
    reason_code: ReasonCode
    reason: str
    window_target: DateRange | None = None
    window_actual: DateRange | None = None
    confidence: Confidence


class UnavailableMetric(BaseModel):
    """不可用。**刻意没有 value 字段** —— 见模块 docstring。"""

    status: Literal["unavailable"] = "unavailable"
    reason_code: ReasonCode
    reason: str


# 用 TypeAliasType 而不是裸的 ``MetricValue = Annotated[...]``：后者不是
# generic class，写 ``MetricValue[float]`` 会直接 TypeError。TypeAliasType 是
# PEP 695 泛型别名的 3.10 兼容写法（PEP 695 的 ``type X[T] = ...`` 语法要 3.12，
# 本仓下限是 3.10），Pydantic v2 原生支持它做判别联合。
MetricValue = TypeAliasType(
    "MetricValue",
    Annotated[
        OkMetric[T] | DegradedMetric[T] | UnavailableMetric,
        Field(discriminator="status"),
    ],
    type_params=(T,),
)


# ---------------------------------------------------------------------------
# 请求模型（§7.2）
# ---------------------------------------------------------------------------


class HoldingItem(BaseModel):
    """一条持仓。``weight`` 缺省表示「让服务端按等权处理」。"""

    symbol: str = Field(min_length=1, max_length=64)
    # ge=0：一期不支持负权重/空头/杠杆（§8.1 非目标），请求层直接拒绝。
    weight: Decimal | None = Field(default=None, ge=0)


class PortfolioPlan(BaseModel):
    """一个方案。单组合诊断只有 1 个；推演 / 多组合对比有 N 个。"""

    plan_id: str = Field(min_length=1, max_length=64)
    label: str | None = Field(default=None, max_length=32)
    # 上限 100 是过渡值（文档 T11）：性能预算基于 n=50，n=200 时 L4 特征分解
    # 的 O(n^3) 与相关矩阵的 JSON 体积都显著超预算。最终数字待真实用户分布确认。
    holdings: list[HoldingItem] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _check_weights(self) -> PortfolioPlan:
        weights = [h.weight for h in self.holdings]
        has_some = any(w is not None for w in weights)
        has_none = any(w is None for w in weights)
        if has_some and has_none:
            # D3（已决）：部分填写、部分缺省 → 拒绝，而不是替用户猜。
            # 猜的两种做法（缺省的按 0 / 缺省的均分剩余）会得出完全不同的组合，
            # 且用户看不出服务端替他选了哪一种。
            raise ValueError(
                "mixed weight input: all holdings must either all specify weight or all omit it"
            )
        if has_some and sum(w for w in weights if w is not None) <= 0:
            raise ValueError("sum of weights must be > 0")
        return self


class SnapshotRequest(BaseModel):
    """``POST /v1/diagnosis/snapshots`` 的请求体。

    用 ``plans`` 而不是单个 ``holdings``，是为了让 before/after 与多组合对比
    走同一个请求结构：编排层只需按 ``len(plans)`` 与 ``intent`` 决定跑几遍。
    """

    plans: list[PortfolioPlan] = Field(min_length=1, max_length=5)
    intent: Intent | None = None  # 缺省 → 按 plans 数量与差异自动判定
    user_level: UserLevel = "retail"  # 渲染偏好，与付费无关（D6）
    as_of_date: date | None = None  # 缺省 → 最近交易日
    spec_version: str | None = Field(default=None, max_length=32)
    # 契约先行：一期只靠 request_hash 兜底，不单独实现幂等键存储与查重（§8.1）。
    idempotency_key: str | None = Field(default=None, max_length=128)


# ---------------------------------------------------------------------------
# 响应模型（§7.3）
# ---------------------------------------------------------------------------


class CovarianceSpec(BaseModel):
    """本次实际用了哪种协方差方法、算了哪些。

    进顶层响应是刻意的：一期是历史降级口径，前端与用户都必须看得到。
    """

    primary: str
    computed: list[str]


class CorrelationBlock(BaseModel):
    """相关性按方法并列。

    前瞻与历史两种口径差异大本身就是风险信号（PDF §4.1.4 评审批注），
    所以差异是**输出项**而不是中间过程。
    """

    by_method: dict[str, MetricValue[float]]
    # 仅当 computed 有多于一种方法时非空。公式待指标文档定义（复审遗留项）。
    divergence: MetricValue[float] | None = None


class ExposureSection(BaseModel):
    """模块 A：构成与敞口。"""

    topn: MetricValue[float]
    hhi: MetricValue[float]
    l1_count: MetricValue[int]
    l2_effective_count: MetricValue[float]
    industry_distribution: MetricValue[dict[str, float]]
    market_distribution: MetricValue[dict[str, float]]
    asset_category_distribution: MetricValue[dict[str, float]]
    style_distribution: MetricValue[dict[str, float]]
    lookthrough_coverage: MetricValue[float]

    # 覆盖率字段族（D4）：归一化前后的权重构成必须并存。
    # 只给归一化后的结果，会把「10 只里有 3 只没解析出来」渲染成一个
    # 看起来完整的 7 只组合，用户完全看不出缺了东西。
    input_weight: float
    resolved_weight: float
    unresolved_weight: float
    calculation_coverage_ratio: float
    normalized_within_resolved_subset: bool


class RiskSection(BaseModel):
    """模块 B：风险。"""

    volatility: MetricValue[float]
    beta: MetricValue[float]
    max_drawdown: MetricValue[float]
    current_drawdown: MetricValue[float]
    var: MetricValue[float]
    cvar: MetricValue[float]
    risk_contribution: MetricValue[dict[str, float]]
    marginal_risk_contribution: MetricValue[dict[str, float]]
    l3_effective_count: MetricValue[float]
    l4_effective_count: MetricValue[float]
    # SSE 批次 2 推送时为 null（那时还没算出来），批次 4 补齐；
    # GET /result 全量返回时恒非空。见 §7.5。
    stress_scenarios: MetricValue[list[dict]] | None = None


class AttributionSection(BaseModel):
    """模块 C：归因与分位。一期整节为 None（缺口 G6 口径未定）。"""

    return_attribution: MetricValue[dict[str, float]]  # market/industry/style/specific
    beta_vs_alpha: MetricValue[dict[str, float]]
    risk_attribution: MetricValue[dict[str, float]]
    historical_percentile: MetricValue[dict[str, float]]


class StructureSection(BaseModel):
    """模块 D：关系与结构。"""

    correlation: CorrelationBlock
    avg_pairwise_correlation: MetricValue[float]
    high_correlation_pairs: MetricValue[list[tuple[str, str, float]]]
    hidden_exposure: MetricValue[float]
    overlap_with_new: MetricValue[float] | None = None


class BlindspotHit(BaseModel):
    """一个盲点检测器的判定结果。"""

    detector: str  # 'pseudo_diversification' / 'style_bet' / 'industry_concentration' / ...
    triggered: bool
    severity: Literal["low", "medium", "high"] | None = None
    message: str
    # 因数据不足而**未能判定**时填。triggered=False 有两种含义
    # （查了没触发 / 压根没法查），靠这个字段区分。
    reason_code: ReasonCode | None = None


class PortfolioProfile(BaseModel):
    """整体画像，对应报告 Section 0。"""

    label: str  # 如 '过度集中型'
    top_findings: list[str]  # Top 3 发现
    confidence: Confidence
    data_status: Literal["complete", "partial", "degraded"]


class ComparisonSection(BaseModel):
    """模块 E：推演与对比。一期恒为 None（属 P2-b）。"""

    deltas: dict[str, MetricValue[float]]
    marginal_impact: MetricValue[float]
    intent_effect_gap: list[str]


class DataQualityReport(BaseModel):
    """数据质量清单，同时是 ``GET /data-quality`` 的响应体。"""

    unresolved_symbols: list[str] = Field(default_factory=list)
    duplicated_symbols: list[str] = Field(default_factory=list)
    suspended_or_delisted: list[str] = Field(default_factory=list)
    new_listings_short_window: list[str] = Field(default_factory=list)
    lookthrough_gaps: list[str] = Field(default_factory=list)
    coverage_summary: dict[str, float] = Field(default_factory=dict)
    forced_disclosures: list[str] = Field(default_factory=list)


class PlanResult(BaseModel):
    """单个方案的完整计算结果。

    这也是 ``diag.diagnosis_run.payload`` 的存储形状 —— run 的粒度是 plan
    而不是 snapshot（T17），所以 payload 存的是 PlanResult 而非 DiagnosisResult。
    """

    plan_id: str
    label: str | None = None
    weight_mode: WeightMode
    section_a: ExposureSection
    # B/C/D 可空是**类型层面**的设计，不是偷懒：口径挂起在类型上体现出来，
    # 前端就必须处理缺失分支，无法假装有数。
    section_b: RiskSection | None = None
    section_c: AttributionSection | None = None
    section_d: StructureSection | None = None
    blindspots: list[BlindspotHit] = Field(default_factory=list)
    profile: PortfolioProfile


class DiagnosisResult(BaseModel):
    """``GET /v1/diagnosis/snapshots/{id}/result`` 的响应体。"""

    snapshot_id: UUID
    spec_version: str
    cov: CovarianceSpec
    as_of_date: date
    report_mode: ReportMode
    run_status: RunStatus
    plans: list[PlanResult]
    comparison: ComparisonSection | None = None
    disclosures: list[str] = Field(default_factory=list)
    data_quality: DataQualityReport
    # status=failed 时非空。这是「计算失败」而非「数据降级」，与 5xx 的
    # 「系统故障」也是两回事，三者语义严格分离（§7.6）。
    error_reason: str | None = None


class SnapshotAccepted(BaseModel):
    """``POST /snapshots`` 的响应体。"""

    snapshot_id: UUID
    run_status: RunStatus
    report_mode: ReportMode
    # 202 时前端据此决定多久后轮询 /result。
    retry_after: int | None = None


class SpecVersionInfo(BaseModel):
    """``GET /spec-versions`` / ``/spec-versions/current`` 的条目。"""

    spec_version: str
    factor_model: str | None = None
    factor_model_version: str | None = None
    params: dict[str, object]
    effective_from: date
    effective_to: date | None = None
    is_active: bool


class ShareTokenCreated(BaseModel):
    """``POST /snapshots/{id}/share`` 的响应体。"""

    token: str
    expires_at: str


class ReportBlock(BaseModel):
    """报告里的一个展示块。

    .. warning::
       **契约待产品确认**。设计文档 §8.1 只给了 Section 0~6 的语义列表，
       没有定义块级字段模型。这里按「标签 + 值 + 状态」的最小形状机械组装，
       接入真实前端设计稿后大概率要调整。不要在它上面堆前端专用字段。
    """

    key: str
    label: str
    value: object | None = None
    status: MetricStatus = MetricStatus.OK
    reason: str | None = None


class ReportSection(BaseModel):
    """报告的一节，对应设计文档 §8.1 的 Section 0~6。"""

    section_id: str
    title: str
    blocks: list[ReportBlock] = Field(default_factory=list)


class DiagnosisReport(BaseModel):
    """``GET /snapshots/{id}/report`` 的响应体：按 user_level 裁剪后的报告。"""

    snapshot_id: UUID
    report_mode: ReportMode
    user_level: UserLevel
    sections: list[ReportSection]
    disclosures: list[str] = Field(default_factory=list)


__all__ = [
    "AttributionSection",
    "BlindspotHit",
    "ComparisonSection",
    "Confidence",
    "CorrelationBlock",
    "CovarianceSpec",
    "DataQualityReport",
    "DateRange",
    "DegradedMetric",
    "DiagnosisReport",
    "DiagnosisResult",
    "ExposureSection",
    "HoldingItem",
    "Intent",
    "MetricStatus",
    "MetricValue",
    "OkMetric",
    "PlanResult",
    "PortfolioPlan",
    "PortfolioProfile",
    "ReasonCode",
    "ReportBlock",
    "ReportMode",
    "ReportSection",
    "RiskSection",
    "RunStatus",
    "ShareTokenCreated",
    "SnapshotAccepted",
    "SnapshotRequest",
    "SpecVersionInfo",
    "StructureSection",
    "UnavailableMetric",
    "UserLevel",
    "WeightMode",
]
