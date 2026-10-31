// 持仓诊断接口类型。照 gr_api.schemas.diagnosis（请求）与
// gr_api.schemas.diagnosis_response（响应）的 JSON 模式输出写（D-007），
// 不照设计稿写：日期是 ISO 字符串，Decimal 序列化成字符串，UUID 是字符串。

// ==== 请求 ====

export interface HoldingInput {
  symbol: string
  /** 缺省表示由后端按去重后的标的等权；同一方案须全填或全不填 */
  weight?: string
}

export interface PortfolioPlanInput {
  plan_id: string
  label?: string
  holdings: HoldingInput[]
}

export interface OptionWindow {
  start: string
  end: string
}

export interface CalculationOptions {
  industry_scheme?: string
  benchmark?: string
  correlation_window?: OptionWindow
  beta_window?: OptionWindow
  replay_start?: string
  stats_window?: OptionWindow
}

export type Intent =
  | 'single_portfolio'
  | 'single_instrument'
  | 'rebalance_amount'
  | 'rebalance_holding'
  | 'multi_portfolio'

export interface SnapshotRequest {
  plans: PortfolioPlanInput[]
  intent?: Intent
  as_of_date?: string
  spec_version?: string
  options?: CalculationOptions
}

export type OptionField =
  | 'industry_scheme'
  | 'benchmark'
  | 'correlation_window'
  | 'beta_window'
  | 'replay_start'
  | 'stats_window'

/** 只覆盖显式给出的字段；同一字段不能既设置又恢复默认 */
export interface RecomputeRequest {
  options?: CalculationOptions
  reset_to_default?: OptionField[]
}

export type UserLevel = 'retail' | 'pro'

// ==== 状态三态 ====

export type ReasonCode =
  | 'factor_model_unavailable'
  | 'history_insufficient'
  | 'coverage_below_threshold'
  | 'spec_not_defined'
  | 'lookthrough_incomplete'
  | 'benchmark_missing'
  | 'new_listing_short_window'
  | 'feature_not_available'
  | 'not_applicable'
  | 'data_not_validated'
  | 'data_stale'
  | 'execution_undetermined'
  | 'zero_variance'
  | 'replay_terminated'
  | 'valuation_lagged'

export type Confidence = 'high' | 'medium' | 'low'

export interface DateRange {
  start: string
  end: string
}

interface MetricWindow {
  window_target?: DateRange | null
  window_actual?: DateRange | null
  sample_count?: number | null
}

export interface OkMetric<T> extends MetricWindow {
  status: 'ok'
  value: T
  method: string
  confidence?: Confidence
}

export interface DegradedMetric<T> extends MetricWindow {
  status: 'degraded'
  value: T
  method: string
  reason_code: ReasonCode
  reason: string
  confidence: Confidence
}

/** 刻意没有 value：不可用结果不能被渲染成 0 */
export interface UnavailableMetric extends MetricWindow {
  status: 'unavailable'
  reason_code: ReasonCode
  reason: string
}

export type MetricValue<T> = OkMetric<T> | DegradedMetric<T> | UnavailableMetric

export interface ErrorInfo {
  code: string
  message: string
  retryable: boolean
  issues: ErrorIssue[]
}

export interface ErrorIssue {
  /** JSON Pointer，如 /plans/0/holdings/2/symbol */
  path: string
  code: string
  message: string
}

/** 诊断接口的错误体不走 {code, message, data} 信封 */
export interface DiagnosisErrorResponse {
  request_id: string
  error: ErrorInfo
}

export type SectionResult<T> =
  | { status: 'ready'; value: T }
  | { status: 'unavailable'; reason_code: ReasonCode; reason: string }
  | { status: 'failed'; error: ErrorInfo }

// ==== 输入回显与数据质量 ====

export interface HoldingEcho {
  input_index: number
  input_symbol: string
  input_weight: string | null
  normalized_symbol: string
  instrument_id: number | null
  name: string | null
  status: 'resolved' | 'unresolved' | 'duplicate' | 'zero_weight'
  merged_into_input_index: number | null
}

export interface CalculationHolding {
  instrument_id: number
  symbol: string
  name: string
  /** 合并后、对完整输入分母的份额 */
  input_share: number
  /** 已识别子集内的归一化计算权重 */
  calculation_weight: number
}

export interface PlanInputSummary {
  weight_mode: 'user' | 'equal'
  holdings: HoldingEcho[]
  calculation_holdings: CalculationHolding[]
  input_weight: 1
  resolved_weight: number
  unresolved_weight: number
  calculation_coverage_ratio: number
  normalized_within_resolved_subset: boolean
}

export interface DataQualityIssue {
  code: string
  reason: string
  paths: string[]
}

export interface PlanDataQuality {
  plan_id: string
  issues: DataQualityIssue[]
  coverage_summary: Record<string, number>
  forced_disclosures: string[]
}

export interface DataQualityReport {
  plans: PlanDataQuality[]
  forced_disclosures: string[]
}

// ==== 计算参数与模型 ====

export interface ResolvedCalculationOptions {
  industry_scheme: string | null
  industry_scheme_version: string | null
  benchmark_instrument_id: number | null
  benchmark_version: string | null
  correlation_window: OptionWindow
  beta_window: OptionWindow
  replay_start: string | null
  stats_window: OptionWindow | null
}

export interface ModelRef {
  model_id: string
  model_version: string
  model_date: string
}

export interface CovarianceSpec {
  requested: string[]
  forward_model: ModelRef | null
  primary: string | null
  computed: string[]
}

export interface MethodValues<T> {
  primary: string | null
  by_method: Record<string, MetricValue<T>>
}

export interface CorrelationMatrix {
  instrument_ids: number[]
  matrix: number[][]
}

export interface CorrelationBlock {
  primary: string | null
  by_method: Record<string, MetricValue<CorrelationMatrix>>
  divergence: MetricValue<number>
}

// ==== 模块 A ====

export interface TopNItem {
  n: 1 | 3 | 5
  actual_count: number
  weight: number
}

export interface MaxIndustry {
  industry_code: string
  industry_name: string
  weight: number
}

export interface InstrumentFacts {
  /** 亿元 */
  total_mv_yi: MetricValue<number>
  pb: MetricValue<number>
  valuation_date: string | null
  /** 小数，可为负 */
  roe: MetricValue<number>
  roe_report_year: number | null
  roe_ann_date: string | null
}

export interface ExposureMetrics {
  topn: MetricValue<TopNItem[]>
  hhi: MetricValue<number>
  l1_count: MetricValue<number>
  l2_effective_count: MetricValue<number>
  industry_distribution: MetricValue<Record<string, number>>
  max_industry: MetricValue<MaxIndustry>
  market_distribution: MetricValue<Record<string, number>>
  asset_category_distribution: MetricValue<Record<string, number>>
  mktcap_distribution: MetricValue<Record<string, number>>
  pb_distribution: MetricValue<Record<string, number>>
  /** 键为 instrument_id 字符串 */
  instrument_facts: MetricValue<Record<string, InstrumentFacts>>
  lookthrough_coverage: MetricValue<number>
}

// ==== 模块 B／C／D（一期均不可用，结构先照后端定义） ====

export interface InstrumentBeta {
  instrument_id: number
  historical_volatility: MetricValue<number>
  beta: MetricValue<number>
  benchmark_correlation: MetricValue<number>
}

export interface RiskSourceShare {
  kind: 'factor' | 'idiosyncratic'
  factor_code: string | null
  instrument_id: number | null
  share: number
}

export interface RiskSection {
  volatility: MethodValues<number>
  instrument_betas: MetricValue<InstrumentBeta[]>
  risk_contribution: MetricValue<Record<string, number>>
  risk_contribution_ratio: MetricValue<Record<string, number>>
  marginal_risk_contribution: MetricValue<Record<string, number>>
  l3_effective_count: MetricValue<number>
  l4_effective_count: MetricValue<number>
  l4_market_source_share: MetricValue<number>
  l4_largest_source: MetricValue<RiskSourceShare>
}

export interface UnexecutedPurchase {
  instrument_id: number
  amount_share: number
  reason: 'suspended_at_open' | 'limit_up_at_open'
  waiting_days: number
}

export interface ReplaySeries {
  build_start: string
  dates: string[]
  nav: number[]
  stock_position: number[]
  unexecuted: UnexecutedPurchase[]
  limiting_instrument_ids: number[]
  truncated_at: string | null
  termination_reason:
    | 'execution_undetermined'
    | 'delisted_no_terminal_value'
    | 'valuation_unreliable'
    | null
}

export interface DrawdownDetail {
  value: number
  peak_date: string
  trough_date: string
  recovery_date: string | null
  duration_days: number
}

export interface HistorySection {
  replay: MetricValue<ReplaySeries>
  replay_volatility: MetricValue<number>
  portfolio_beta: MetricValue<number>
  portfolio_benchmark_correlation: MetricValue<number>
  max_drawdown: MetricValue<DrawdownDetail>
  current_drawdown: MetricValue<number>
  var: MetricValue<number>
  cvar: MetricValue<number>
  return_attribution: MetricValue<Record<string, number>>
  beta_vs_alpha: MetricValue<Record<string, number>>
  risk_attribution: MetricValue<Record<string, number>>
  historical_percentile: MetricValue<Record<string, number>>
}

export interface HighCorrelationPair {
  left_instrument_id: number
  right_instrument_id: number
  correlation: number
}

export interface StructureSection {
  correlation: CorrelationBlock
  avg_pairwise_correlation: MethodValues<number>
  high_correlation_pairs: MethodValues<HighCorrelationPair[]>
  style_exposure: MetricValue<Record<string, number>>
  hidden_exposure: MetricValue<number>
}

export interface StressScenario {
  scenario_id: string
  label: string
  impact: MetricValue<number>
}

export interface BlindspotHit {
  detector: string
  status: 'triggered' | 'not_triggered' | 'unavailable'
  severity: 'low' | 'medium' | 'high' | null
  message: string
  reason_code: ReasonCode | null
}

export interface PortfolioProfile {
  label: string
  top_findings: string[]
  confidence: Confidence
  data_status: 'complete' | 'partial' | 'degraded'
}

export type RunStatus = 'pending' | 'running' | 'succeeded' | 'partially_succeeded' | 'failed'
export type TerminalStatus = 'succeeded' | 'partially_succeeded' | 'failed'
export type ReportMode = 'standard' | 'single_instrument' | 'compare'

export interface PlanResult {
  plan_id: string
  label: string | null
  run_status: TerminalStatus
  error: ErrorInfo | null
  input: PlanInputSummary
  cov: CovarianceSpec
  section_a: SectionResult<ExposureMetrics>
  section_b: SectionResult<RiskSection>
  section_c: SectionResult<HistorySection>
  section_d: SectionResult<StructureSection>
  stress_scenarios: SectionResult<StressScenario[]>
  blindspots: SectionResult<BlindspotHit[]>
  profile: SectionResult<PortfolioProfile>
}

export interface SnapshotMeta {
  snapshot_id: string
  schema_version: 'diagnosis.v1'
  spec_version: string
  as_of_date: string
  data_fingerprint: string
  data_snapshot_at: string
  resolved_intent: Intent
  report_mode: ReportMode
  requested_cov_methods: string[]
  options: ResolvedCalculationOptions
  base_snapshot_id: string | null
  historical_result: boolean
}

export type SectionId =
  | 'section_a'
  | 'section_b'
  | 'section_c'
  | 'section_d'
  | 'stress_scenarios'
  | 'blindspots'
  | 'profile'

export interface PlanProgress {
  plan_id: string
  label: string | null
  run_status: RunStatus
  sections: Record<SectionId, 'pending' | 'running' | 'ready' | 'unavailable' | 'failed'>
  error: ErrorInfo | null
}

export interface SnapshotProgress extends SnapshotMeta {
  run_status: 'pending' | 'running'
  plans: PlanProgress[]
}

export interface SnapshotAccepted extends SnapshotMeta {
  run_status: RunStatus
  plans: PlanProgress[]
  links: { result: string; report: string; stream: string; data_quality: string }
}

export interface DataQualityResponse extends SnapshotMeta {
  run_status: TerminalStatus
  data_quality: DataQualityReport
}

export interface SpecVersionInfo {
  spec_version: string
  effective_from: string
  effective_to: string | null
  is_active: boolean
  /** 口径参数（阈值、窗口、分档等），结构以后端口径版本为准；前端不要抄成常量 */
  params: Record<string, unknown>
}

export interface SpecVersionList {
  items: SpecVersionInfo[]
}

export interface DiagnosisResult extends SnapshotMeta {
  run_status: TerminalStatus
  plans: PlanResult[]
  comparison: SectionResult<unknown>
  disclosures: string[]
  data_quality: DataQualityReport
}

// ==== 报告（§7.3.4） ====

export interface MetricCardItem {
  metric_id: string
  label: string
  value: MetricValue<number>
  format: 'percent' | 'percentage_point' | 'number' | 'integer'
  decimals: number
}

export type ReportBlock =
  | { type: 'text'; text: string }
  | { type: 'metric_cards'; items: MetricCardItem[] }
  | {
      type: 'distribution'
      metric_id: string
      labels: Record<string, string>
      values: MetricValue<Record<string, number>>
    }
  | { type: 'correlation_matrix'; labels: Record<string, string>; values: CorrelationBlock }
  | { type: 'holdings'; input: PlanInputSummary }
  | { type: 'replay_chart'; values: MetricValue<ReplaySeries>; stats_window: DateRange | null }

export type ReportSectionKind =
  | 'profile'
  | 'exposure'
  | 'diversification'
  | 'risk'
  | 'style'
  | 'instrument'
  | 'comparison'
  | 'limitations'
  | 'summary'

export interface ReportSection {
  section_id: string
  plan_id: string | null
  kind: ReportSectionKind
  title: string
  content: SectionResult<ReportBlock[]>
}

export interface ReportResponse extends SnapshotMeta {
  user_level: UserLevel
  run_status: TerminalStatus
  sections: ReportSection[]
  disclosures: string[]
  data_quality: DataQualityReport
}
