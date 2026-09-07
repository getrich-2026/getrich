"""网页诊断响应契约，对齐表与接口设计 v0.3.0 §7.3。

数值、整节状态与报告组件使用判别联合；JSON 不增加 root 层。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    JsonValue,
    RootModel,
    model_validator,
)


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
UserLevel = Literal["retail", "pro"]

T = TypeVar("T")
Ratio = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
RunStatus = Literal["pending", "running", "succeeded", "partially_succeeded", "failed"]
TerminalStatus = Literal["succeeded", "partially_succeeded", "failed"]
ReportMode = Literal["standard", "single_instrument", "compare"]


class ReasonCode(StrEnum):
    FACTOR_MODEL_UNAVAILABLE = "factor_model_unavailable"
    HISTORY_INSUFFICIENT = "history_insufficient"
    COVERAGE_BELOW_THRESHOLD = "coverage_below_threshold"
    SPEC_NOT_DEFINED = "spec_not_defined"
    LOOKTHROUGH_INCOMPLETE = "lookthrough_incomplete"
    BENCHMARK_MISSING = "benchmark_missing"
    NEW_LISTING_SHORT_WINDOW = "new_listing_short_window"
    FEATURE_NOT_AVAILABLE = "feature_not_available"
    NOT_APPLICABLE = "not_applicable"


class DateRange(ApiModel):
    start: date
    end: date

    @model_validator(mode="after")
    def check_order(self) -> DateRange:
        if self.start > self.end:
            raise ValueError("start must not be after end")
        return self


class ErrorIssue(ApiModel):
    path: str  # JSON Pointer；请求头错误用 /headers/Idempotency-Key
    code: str
    message: str


class ErrorInfo(ApiModel):
    code: str  # 稳定机器码，不暴露异常堆栈
    message: str
    retryable: bool
    issues: list[ErrorIssue] = Field(default_factory=list)


class ErrorResponse(ApiModel):
    request_id: str
    error: ErrorInfo


class OkMetric(ApiModel, Generic[T]):
    status: Literal["ok"] = "ok"
    value: T
    method: str
    window_target: DateRange | None = None
    window_actual: DateRange | None = None
    confidence: Literal["high", "medium", "low"] = "high"


class DegradedMetric(ApiModel, Generic[T]):
    status: Literal["degraded"] = "degraded"
    value: T
    method: str
    reason_code: ReasonCode
    reason: str
    window_target: DateRange | None = None
    window_actual: DateRange | None = None
    confidence: Literal["high", "medium", "low"]


class UnavailableMetric(ApiModel):
    status: Literal["unavailable"] = "unavailable"
    reason_code: ReasonCode
    reason: str


class MetricValue(
    RootModel[
        Annotated[
            OkMetric[T] | DegradedMetric[T] | UnavailableMetric,
            Field(discriminator="status"),
        ]
    ],
    Generic[T],
):
    pass


class ReadySection(ApiModel, Generic[T]):
    status: Literal["ready"] = "ready"
    value: T


class UnavailableSection(ApiModel):
    status: Literal["unavailable"] = "unavailable"
    reason_code: ReasonCode
    reason: str


class FailedSection(ApiModel):
    status: Literal["failed"] = "failed"
    error: ErrorInfo


class SectionResult(
    RootModel[
        Annotated[
            ReadySection[T] | UnavailableSection | FailedSection,
            Field(discriminator="status"),
        ]
    ],
    Generic[T],
):
    pass


class HoldingEcho(ApiModel):
    input_index: int = Field(ge=0)
    input_symbol: str
    input_weight: Decimal | None
    normalized_symbol: str
    instrument_id: int | None
    name: str | None
    status: Literal["resolved", "unresolved", "duplicate", "zero_weight"]
    merged_into_input_index: int | None = None


class CalculationHolding(ApiModel):
    instrument_id: int
    symbol: str
    name: str
    input_share: Ratio  # 合并后、对完整输入分母的份额
    calculation_weight: Ratio  # 已解析子集内的归一化权重


class PlanInputSummary(ApiModel):
    weight_mode: Literal["user", "equal"]
    holdings: list[HoldingEcho]
    calculation_holdings: list[CalculationHolding]
    input_weight: Literal[1.0] = 1.0  # 始终为份额 1，不是原始金额或百分数之和
    resolved_weight: Ratio
    unresolved_weight: Ratio
    calculation_coverage_ratio: Ratio
    normalized_within_resolved_subset: bool

    @model_validator(mode="after")
    def check_weights(self) -> PlanInputSummary:
        if abs(self.resolved_weight + self.unresolved_weight - 1) > 1e-6:
            raise ValueError("input shares must sum to one")
        if abs(self.calculation_coverage_ratio - self.resolved_weight) > 1e-6:
            raise ValueError("coverage must equal resolved share")
        if (
            self.calculation_holdings
            and abs(sum(h.calculation_weight for h in self.calculation_holdings) - 1) > 1e-6
        ):
            raise ValueError("calculation weights must sum to one")
        if self.normalized_within_resolved_subset != (self.unresolved_weight > 0):
            raise ValueError("subset normalization must reflect unresolved positive share")
        return self


class DataQualityIssue(ApiModel):
    code: str
    reason: str
    paths: list[str]  # 该 plan 下 /holdings/0 或 /section_b/value/var 等


class PlanDataQuality(ApiModel):
    plan_id: PlanId
    issues: list[DataQualityIssue]
    coverage_summary: dict[str, Ratio]
    forced_disclosures: list[str]


class DataQualityReport(ApiModel):
    plans: list[PlanDataQuality]
    forced_disclosures: list[str]  # snapshot 公共声明；方案专属声明留在 plans


class CovarianceSpec(ApiModel):
    requested: list[str]
    primary: str | None  # 实际驱动主指标的方法；全不可用时为 null
    computed: list[str]  # 此 plan 实际成功计算的方法

    @model_validator(mode="after")
    def check_primary(self) -> CovarianceSpec:
        if self.primary is not None and self.primary not in self.computed:
            raise ValueError("primary must be a computed method")
        if bool(self.computed) != (self.primary is not None):
            raise ValueError("primary is null exactly when no method was computed")
        return self


class MethodValues(ApiModel, Generic[T]):
    primary: str | None
    by_method: dict[str, MetricValue[T]]


class CorrelationMatrix(ApiModel):
    instrument_ids: list[int]
    matrix: list[list[Annotated[float, Field(ge=-1, le=1, allow_inf_nan=False)]]]

    @model_validator(mode="after")
    def check_dimensions(self) -> CorrelationMatrix:
        n = len(self.instrument_ids)
        if self.instrument_ids != sorted(set(self.instrument_ids)):
            raise ValueError("matrix instrument_ids must be unique and sorted")
        if len(self.matrix) != n or any(len(row) != n for row in self.matrix):
            raise ValueError("matrix dimensions must match instrument_ids")
        for i in range(n):
            if abs(self.matrix[i][i] - 1) > 1e-6:
                raise ValueError("correlation diagonal must be one")
            if any(abs(self.matrix[i][j] - self.matrix[j][i]) > 1e-6 for j in range(i)):
                raise ValueError("correlation matrix must be symmetric")
        return self


class CorrelationBlock(ApiModel):
    primary: str | None
    by_method: dict[str, MetricValue[CorrelationMatrix]]
    divergence: MetricValue[FiniteFloat]  # 不足两种方法时 unavailable / not_applicable


class ExposureMetrics(ApiModel):
    topn: MetricValue[Ratio]
    hhi: MetricValue[Ratio]
    l1_count: MetricValue[int]
    l2_effective_count: MetricValue[FiniteFloat]
    industry_distribution: MetricValue[dict[str, Ratio]]
    market_distribution: MetricValue[dict[str, Ratio]]
    asset_category_distribution: MetricValue[dict[str, Ratio]]
    style_distribution: MetricValue[dict[str, Ratio]]
    lookthrough_coverage: MetricValue[Ratio]


class StressScenario(ApiModel):
    scenario_id: str
    label: str
    impact: MetricValue[FiniteFloat]  # 收益率小数，例如 -0.032 表示 -3.2%


class RiskSection(ApiModel):
    volatility: MethodValues[FiniteFloat]
    beta: MetricValue[FiniteFloat]
    risk_contribution: MetricValue[dict[str, FiniteFloat]]
    risk_contribution_ratio: MetricValue[dict[str, FiniteFloat]]
    marginal_risk_contribution: MetricValue[dict[str, FiniteFloat]]
    l3_effective_count: MetricValue[FiniteFloat]
    l4_effective_count: MetricValue[FiniteFloat]


class HistorySection(ApiModel):
    max_drawdown: MetricValue[FiniteFloat]
    current_drawdown: MetricValue[FiniteFloat]
    var: MetricValue[FiniteFloat]
    cvar: MetricValue[FiniteFloat]
    return_attribution: MetricValue[dict[str, FiniteFloat]]
    beta_vs_alpha: MetricValue[dict[str, FiniteFloat]]
    risk_attribution: MetricValue[dict[str, FiniteFloat]]
    historical_percentile: MetricValue[dict[str, Ratio]]


class HighCorrelationPair(ApiModel):
    left_instrument_id: int
    right_instrument_id: int
    correlation: Annotated[float, Field(ge=-1, le=1, allow_inf_nan=False)]


class StructureSection(ApiModel):
    correlation: CorrelationBlock
    avg_pairwise_correlation: MetricValue[FiniteFloat]
    high_correlation_pairs: MetricValue[list[HighCorrelationPair]]
    hidden_exposure: MetricValue[FiniteFloat]


class BlindspotHit(ApiModel):
    detector: str
    status: Literal["triggered", "not_triggered", "unavailable"]
    severity: Literal["low", "medium", "high"] | None
    message: str
    reason_code: ReasonCode | None

    @model_validator(mode="after")
    def check_status(self) -> BlindspotHit:
        if self.status == "unavailable" and (self.reason_code is None or self.severity is not None):
            raise ValueError("unavailable detector needs reason_code and no severity")
        if self.status == "triggered" and self.severity is None:
            raise ValueError("triggered detector needs severity")
        if self.status == "not_triggered" and self.severity is not None:
            raise ValueError("not_triggered detector must not have severity")
        return self


class PortfolioProfile(ApiModel):
    label: str
    top_findings: list[str] = Field(max_length=3)
    confidence: Literal["high", "medium", "low"]
    data_status: Literal["complete", "partial", "degraded"]


class CalculationPayload(ApiModel):
    """PG/Redis 共享载体：仅依赖 calculation_hash，不含请求标识或输入覆盖率。"""

    cov: CovarianceSpec
    section_a: SectionResult[ExposureMetrics]
    section_b: SectionResult[RiskSection]
    section_c: SectionResult[HistorySection]
    section_d: SectionResult[StructureSection]
    stress_scenarios: SectionResult[list[StressScenario]]


class PairComparison(ApiModel):
    before_plan_id: PlanId
    after_plan_id: PlanId
    deltas: dict[str, MetricValue[FiniteFloat]]
    marginal_impact: MetricValue[FiniteFloat]
    overlap_with_new: MetricValue[FiniteFloat]
    intent_effect_gap: list[str]


class ComparisonSection(ApiModel):
    pairs: list[PairComparison]


class PlanResult(CalculationPayload):
    plan_id: PlanId
    label: str | None
    run_status: TerminalStatus
    error: ErrorInfo | None
    input: PlanInputSummary
    blindspots: SectionResult[list[BlindspotHit]]
    profile: SectionResult[PortfolioProfile]

    @model_validator(mode="after")
    def check_error(self) -> PlanResult:
        if (self.run_status == "failed") != (self.error is not None):
            raise ValueError("plan error is required exactly for failed plans")
        return self


class SnapshotMeta(ApiModel):
    snapshot_id: UUID
    schema_version: Literal["diagnosis.v1"] = "diagnosis.v1"
    spec_version: str
    as_of_date: date
    data_fingerprint: str
    data_snapshot_at: AwareDatetime
    resolved_intent: Intent
    report_mode: ReportMode
    requested_cov_methods: list[str]


class DiagnosisResult(SnapshotMeta):
    run_status: TerminalStatus
    plans: list[PlanResult] = Field(min_length=1, max_length=5)
    comparison: SectionResult[ComparisonSection]
    disclosures: list[str]
    data_quality: DataQualityReport


SectionId = Literal[
    "section_a", "section_b", "section_c", "section_d", "stress_scenarios", "blindspots", "profile"
]


class SnapshotLinks(ApiModel):
    result: str
    report: str
    stream: str
    data_quality: str


class PlanProgress(ApiModel):
    plan_id: PlanId
    label: str | None
    run_status: RunStatus
    sections: dict[SectionId, Literal["pending", "running", "ready", "unavailable", "failed"]]
    error: ErrorInfo | None


class SnapshotProgress(SnapshotMeta):
    run_status: Literal["pending", "running"]
    plans: list[PlanProgress]


class SnapshotAccepted(SnapshotMeta):
    run_status: RunStatus
    plans: list[PlanProgress]
    links: SnapshotLinks


class DataQualityResponse(SnapshotMeta):
    run_status: TerminalStatus
    data_quality: DataQualityReport


class SpecVersionInfo(ApiModel):
    spec_version: str
    effective_from: date
    effective_to: date | None
    is_active: bool
    params: dict[str, JsonValue]  # 完整配置键及校验以 §5.5 为准


class SpecVersionList(ApiModel):
    items: list[SpecVersionInfo]


class MetricCard(ApiModel):
    metric_id: str
    label: str
    value: MetricValue[FiniteFloat | int]
    format: Literal["percent", "percentage_point", "number", "integer"]
    decimals: int = Field(ge=0, le=8)


class TextBlock(ApiModel):
    type: Literal["text"] = "text"
    text: str


class MetricCardsBlock(ApiModel):
    type: Literal["metric_cards"] = "metric_cards"
    items: list[MetricCard]


class DistributionBlock(ApiModel):
    type: Literal["distribution"] = "distribution"
    metric_id: str
    labels: dict[str, str]
    values: MetricValue[dict[str, Ratio]]


class CorrelationChartBlock(ApiModel):
    type: Literal["correlation_matrix"] = "correlation_matrix"
    labels: dict[str, str]  # instrument_id 字符串 -> 名称
    values: CorrelationBlock


class HoldingsBlock(ApiModel):
    type: Literal["holdings"] = "holdings"
    input: PlanInputSummary


ReportBlock = Annotated[
    TextBlock | MetricCardsBlock | DistributionBlock | CorrelationChartBlock | HoldingsBlock,
    Field(discriminator="type"),
]


class ReportSection(ApiModel):
    section_id: str  # 稳定唯一 ID，例如 p1:risk 或 comparison
    plan_id: PlanId | None  # snapshot 级区块为 null
    kind: Literal[
        "profile",
        "exposure",
        "diversification",
        "risk",
        "style",
        "instrument",
        "comparison",
        "limitations",
        "summary",
    ]
    title: str
    content: SectionResult[list[ReportBlock]]


class ReportResponse(SnapshotMeta):
    user_level: UserLevel
    run_status: TerminalStatus
    sections: list[ReportSection]
    disclosures: list[str]
    data_quality: DataQualityReport


class SharedReportSection(ApiModel):
    title: str
    content: SectionResult[list[ReportBlock]]


class SharedReportResponse(ApiModel):
    report_mode: ReportMode
    sections: list[SharedReportSection]
    disclosures: list[str]
