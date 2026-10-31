"""网页诊断响应契约，对齐表与接口设计 §7.3（含 2026-10-20／21 补充）。

数值、整节状态与报告组件使用判别联合；JSON 不增加 root 层。``UnavailableMetric``
刻意没有 ``value`` 字段：不可用结果在类型层面就构造不成数字，前端只能展示原因。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Generic, Literal, TypeVar
from uuid import UUID

from gr_api.schemas.diagnosis import ApiModel, Intent, OptionWindow, PlanId
from pydantic import (
    AfterValidator,
    AwareDatetime,
    ConfigDict,
    Field,
    FiniteFloat,
    JsonValue,
    RootModel,
    model_validator,
)


UserLevel = Literal["retail", "pro"]

T = TypeVar("T")
Ratio = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
NonPositiveRatio = Annotated[float, Field(ge=-1, le=0, allow_inf_nan=False)]
Correlation = Annotated[float, Field(ge=-1, le=1, allow_inf_nan=False)]
RunStatus = Literal["pending", "running", "succeeded", "partially_succeeded", "failed"]
TerminalStatus = Literal["succeeded", "partially_succeeded", "failed"]
ReportMode = Literal["standard", "single_instrument", "compare"]


class ReasonCode(StrEnum):
    """稳定的机器可读原因码；前端只按码分支，``reason`` 文案仅供展示。"""

    FACTOR_MODEL_UNAVAILABLE = "factor_model_unavailable"
    HISTORY_INSUFFICIENT = "history_insufficient"
    COVERAGE_BELOW_THRESHOLD = "coverage_below_threshold"
    SPEC_NOT_DEFINED = "spec_not_defined"
    LOOKTHROUGH_INCOMPLETE = "lookthrough_incomplete"
    BENCHMARK_MISSING = "benchmark_missing"
    NEW_LISTING_SHORT_WINDOW = "new_listing_short_window"
    FEATURE_NOT_AVAILABLE = "feature_not_available"
    NOT_APPLICABLE = "not_applicable"
    # 2026-10-20 新增（PA-15 I10）
    DATA_NOT_VALIDATED = "data_not_validated"  # 供应商数据未通过接入验证（PA-04、DP-04）
    DATA_STALE = "data_stale"  # 超出 DP-08 过期上限
    EXECUTION_UNDETERMINED = "execution_undetermined"  # 开盘价或交易状态缺失（PA-12）
    ZERO_VARIANCE = "zero_variance"  # 零波动或基准方差为零（PA-10、PA-11）
    REPLAY_TERMINATED = "replay_terminated"  # 统计区间越过回放截断日（PA-15 B4）
    # 2026-10-21 新增（PA-07）
    VALUATION_LAGGED = "valuation_lagged"  # 估值日期早于诊断日期，照常归档但降级


class DateRange(ApiModel):
    """回显用闭区间；请求区间用 :class:`OptionWindow`（PA-15 I5）。"""

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
    sample_count: int | None = Field(default=None, ge=0)
    confidence: Literal["high", "medium", "low"] = "high"


class DegradedMetric(ApiModel, Generic[T]):
    status: Literal["degraded"] = "degraded"
    value: T
    method: str
    reason_code: ReasonCode
    reason: str
    window_target: DateRange | None = None
    window_actual: DateRange | None = None
    sample_count: int | None = Field(default=None, ge=0)
    confidence: Literal["high", "medium", "low"]


class UnavailableMetric(ApiModel):
    status: Literal["unavailable"] = "unavailable"
    reason_code: ReasonCode
    reason: str
    # 样本不足等情形仍须回显目标与实际窗口及有效样本数（PA-09、PA-11、PA-12）
    window_target: DateRange | None = None
    window_actual: DateRange | None = None
    sample_count: int | None = Field(default=None, ge=0)


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


# ---------------------------------------------------------------------------
# 输入回显与数据质量
# ---------------------------------------------------------------------------


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
    calculation_weight: Ratio  # 已解析子集内的归一化权重（§7.8 量化后）


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
    paths: list[str]  # 该 plan 下 /holdings/0 或 /section_a/value/topn 等


class PlanDataQuality(ApiModel):
    plan_id: PlanId
    issues: list[DataQualityIssue]
    coverage_summary: dict[str, Ratio]
    forced_disclosures: list[str]


class DataQualityReport(ApiModel):
    plans: list[PlanDataQuality]
    forced_disclosures: list[str]  # snapshot 公共声明；方案专属声明留在 plans


# ---------------------------------------------------------------------------
# 计算参数与模型身份
# ---------------------------------------------------------------------------


class ResolvedCalculationOptions(ApiModel):
    """解析后的计算参数；进入 calculation_hash 并随结果回显。

    可解析的缺省值一律写成具体值；None 仅表示该项当前不可用（如默认基准未验证），
    相关指标 unavailable。replay_start 是快照级目标建仓起点，各方案实际起点见
    ``ReplaySeries.build_start``（PA-15 I6）。
    """

    industry_scheme: str | None
    industry_scheme_version: str | None
    benchmark_instrument_id: int | None
    benchmark_version: str | None
    correlation_window: OptionWindow
    beta_window: OptionWindow
    replay_start: date | None
    stats_window: OptionWindow | None


class ModelRef(ApiModel):
    """米筐模型身份；模型波动率、RC、L3、L4、模型相关性、风格暴露共用。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, protected_namespaces=())

    model_id: str
    model_version: str
    model_date: date


class CovarianceSpec(ApiModel):
    requested: list[str]
    forward_model: ModelRef | None = None  # forward 已计算时必填
    # 只能是口径版本的 primary_cov_method；该方法未算出时为 null，不以其他方法顶替
    primary: str | None
    computed: list[str]

    @model_validator(mode="after")
    def check_primary(self) -> CovarianceSpec:
        if self.primary is not None and self.primary not in self.computed:
            raise ValueError("primary must be a computed method")
        if ("forward" in self.computed) != (self.forward_model is not None):
            raise ValueError("forward_model is required exactly when forward was computed")
        return self


class MethodValues(ApiModel, Generic[T]):
    primary: str | None
    by_method: dict[str, MetricValue[T]]


class CorrelationMatrix(ApiModel):
    instrument_ids: list[int]
    matrix: list[list[Correlation]]

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
    divergence: MetricValue[FiniteFloat]  # PA-09：一期固定 unavailable / feature_not_available


# ---------------------------------------------------------------------------
# 模块 A：构成与敞口
# ---------------------------------------------------------------------------


class TopNItem(ApiModel):
    n: Literal[1, 3, 5]
    actual_count: int = Field(ge=1)  # 少于 N 只时为实际数量，展示时注明
    weight: Ratio

    @model_validator(mode="after")
    def check_count(self) -> TopNItem:
        if self.actual_count > self.n:
            raise ValueError("actual_count must not exceed n")
        return self


def _check_topn(items: list[TopNItem]) -> list[TopNItem]:
    if sorted(i.n for i in items) != [1, 3, 5]:
        raise ValueError("topn must contain n=1, 3 and 5 exactly once")
    return items


TopNList = Annotated[list[TopNItem], AfterValidator(_check_topn)]


class MaxIndustry(ApiModel):
    industry_code: str
    industry_name: str
    weight: Ratio


class InstrumentFacts(ApiModel):
    """PA-07 个股展示字段；各字段独立表达可用性，不用 0 或缺省值顶替。"""

    total_mv_yi: MetricValue[FiniteFloat]  # 总市值，亿元；入库为元，换算一处完成
    pb: MetricValue[FiniteFloat]  # 原值展示，非正值不截断
    valuation_date: date | None  # 总市值与 PB 的数据日期
    roe: MetricValue[FiniteFloat]  # 最近已披露完整年度加权平均 ROE，小数（可为负）
    roe_report_year: int | None
    roe_ann_date: date | None

    @model_validator(mode="after")
    def check_roe_dates(self) -> InstrumentFacts:
        if self.roe.root.status != "unavailable" and (
            self.roe_report_year is None or self.roe_ann_date is None
        ):
            raise ValueError("roe with value requires roe_report_year and roe_ann_date")
        return self


class ExposureMetrics(ApiModel):
    topn: MetricValue[TopNList]
    hhi: MetricValue[Ratio]
    l1_count: MetricValue[int]
    l2_effective_count: MetricValue[FiniteFloat]
    # 键为行业代码；缺失归入保留键 unclassified，不重新归一化（PA-05）
    industry_distribution: MetricValue[dict[str, Ratio]]
    max_industry: MetricValue[MaxIndustry]
    market_distribution: MetricValue[dict[str, Ratio]]  # 键 cn_a/hk/us/other
    asset_category_distribution: MetricValue[dict[str, Ratio]]
    mktcap_distribution: MetricValue[dict[str, Ratio]]  # 五档 + missing_or_invalid
    pb_distribution: MetricValue[dict[str, Ratio]]  # 五档 + non_positive + missing_or_invalid
    instrument_facts: MetricValue[dict[str, InstrumentFacts]]  # 键为 instrument_id 字符串
    lookthrough_coverage: MetricValue[Ratio]


class StressScenario(ApiModel):
    scenario_id: str
    label: str
    impact: MetricValue[FiniteFloat]  # 收益率小数，例如 -0.032 表示 -3.2%


# ---------------------------------------------------------------------------
# 模块 B：风险
# ---------------------------------------------------------------------------


class InstrumentBeta(ApiModel):
    """PA-11 逐股独立配对样本；PA-20 个股历史年化波动率用个股自身有效日收益。"""

    instrument_id: int
    historical_volatility: MetricValue[FiniteFloat]
    beta: MetricValue[FiniteFloat]
    benchmark_correlation: MetricValue[FiniteFloat]


class RiskSourceShare(ApiModel):
    """L4 风险源身份；正交风险源只与原因子对应，不等同原因子。"""

    kind: Literal["factor", "idiosyncratic"]
    factor_code: str | None = None
    instrument_id: int | None = None
    share: Ratio

    @model_validator(mode="after")
    def check_identity(self) -> RiskSourceShare:
        if self.kind == "factor":
            ok = self.factor_code is not None and self.instrument_id is None
        else:
            ok = self.instrument_id is not None and self.factor_code is None
        if not ok:
            raise ValueError(
                "factor source needs factor_code only; "
                "idiosyncratic source needs instrument_id only"
            )
        return self


class RiskSection(ApiModel):
    volatility: MethodValues[FiniteFloat]  # 一期 by_method 只含 forward（PA-10）
    instrument_betas: MetricValue[list[InstrumentBeta]]
    risk_contribution: MetricValue[dict[str, FiniteFloat]]
    risk_contribution_ratio: MetricValue[dict[str, FiniteFloat]]
    marginal_risk_contribution: MetricValue[dict[str, FiniteFloat]]
    l3_effective_count: MetricValue[FiniteFloat]
    l4_effective_count: MetricValue[FiniteFloat]
    l4_market_source_share: MetricValue[Ratio]
    l4_largest_source: MetricValue[RiskSourceShare]


# ---------------------------------------------------------------------------
# 模块 C：历史回放
# ---------------------------------------------------------------------------


class UnexecutedPurchase(ApiModel):
    """PA-12：区间结束仍无法买入的预留现金。"""

    instrument_id: int
    amount_share: Ratio  # 占区间末总资产的比例
    reason: Literal["suspended_at_open", "limit_up_at_open"]
    waiting_days: int = Field(ge=0)


class ReplaySeries(ApiModel):
    """PA-12 买入持有回放；净值以建仓日开盘前总资产为 1。"""

    build_start: date
    dates: list[date]
    nav: list[Annotated[float, Field(gt=0, allow_inf_nan=False)]]
    stock_position: list[Ratio]  # 应收分红与现金可使其低于 1，不重新归一化
    unexecuted: list[UnexecutedPurchase]
    limiting_instrument_ids: list[int]
    truncated_at: date | None = None
    termination_reason: (
        Literal["execution_undetermined", "delisted_no_terminal_value", "valuation_unreliable"]
        | None
    ) = None

    @model_validator(mode="after")
    def check_lengths(self) -> ReplaySeries:
        if not (len(self.dates) == len(self.nav) == len(self.stock_position)):
            raise ValueError("dates, nav and stock_position must have equal length")
        if (self.truncated_at is None) != (self.termination_reason is None):
            raise ValueError("truncated_at and termination_reason must be set together")
        if self.truncated_at is not None and (
            not self.dates or self.dates[-1] != self.truncated_at
        ):
            raise ValueError("truncated series must end at truncated_at")
        return self


class DrawdownDetail(ApiModel):
    """PA-18：统计区间内的最大回撤路径。"""

    value: NonPositiveRatio
    peak_date: date
    trough_date: date
    recovery_date: date | None
    duration_days: int = Field(ge=0)

    @model_validator(mode="after")
    def check_dates(self) -> DrawdownDetail:
        if self.trough_date < self.peak_date:
            raise ValueError("trough_date must not be before peak_date")
        if self.recovery_date is not None and self.recovery_date <= self.trough_date:
            raise ValueError("recovery_date must be after trough_date")
        return self


class HistorySection(ApiModel):
    replay: MetricValue[ReplaySeries]
    replay_volatility: MetricValue[FiniteFloat]
    portfolio_beta: MetricValue[FiniteFloat]
    portfolio_benchmark_correlation: MetricValue[FiniteFloat]
    max_drawdown: MetricValue[DrawdownDetail]
    current_drawdown: MetricValue[NonPositiveRatio]
    var: MetricValue[FiniteFloat]
    cvar: MetricValue[FiniteFloat]
    return_attribution: MetricValue[dict[str, FiniteFloat]]
    beta_vs_alpha: MetricValue[dict[str, FiniteFloat]]
    risk_attribution: MetricValue[dict[str, FiniteFloat]]
    historical_percentile: MetricValue[dict[str, Ratio]]  # PA-19：一期固定不可用


# ---------------------------------------------------------------------------
# 模块 D：关系与结构
# ---------------------------------------------------------------------------


class HighCorrelationPair(ApiModel):
    left_instrument_id: int
    right_instrument_id: int
    correlation: Correlation


class StructureSection(ApiModel):
    correlation: CorrelationBlock
    avg_pairwise_correlation: MethodValues[FiniteFloat]
    high_correlation_pairs: MethodValues[list[HighCorrelationPair]]  # 严格 >0.7，不取绝对值
    style_exposure: MetricValue[dict[str, FiniteFloat]]  # PA-07：须绑定 cov.forward_model
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
    """PG 共享载体：仅依赖 calculation_hash，不含请求标识或输入覆盖率。"""

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
    options: ResolvedCalculationOptions
    base_snapshot_id: UUID | None = None  # 区间重算来源；新提交为 None
    # PA-14：原数据日期超出 DP-08 时效上限的重算结果为 True，并在 disclosures 中说明
    historical_result: bool = False


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


# ---------------------------------------------------------------------------
# 报告（§7.3.4）
# ---------------------------------------------------------------------------


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


class ReplayChartBlock(ApiModel):
    """PA-12 回放曲线；显示范围只影响前端可见区间，不改统计区间或建仓起点。"""

    type: Literal["replay_chart"] = "replay_chart"
    values: MetricValue[ReplaySeries]
    stats_window: DateRange | None


ReportBlock = Annotated[
    TextBlock
    | MetricCardsBlock
    | DistributionBlock
    | CorrelationChartBlock
    | HoldingsBlock
    | ReplayChartBlock,
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
