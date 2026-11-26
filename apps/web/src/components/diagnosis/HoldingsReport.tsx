import type {
  DataQualityReport,
  DiagnosisResult,
  HistorySection,
  HoldingRiskComparisonBlock,
  HoldingRiskIndustryRow,
  HoldingRiskStockRow,
  MetricValue,
  PlanDataQuality,
  PlanResult,
  ReportResponse,
  SectionResult,
} from '@/types/diagnosis'

const PANEL = 'rounded-xl border border-[var(--gr-border)] bg-[var(--gr-bg-card)] p-5'

function formatPercent(value: number, decimals = 1): string {
  return `${(value * 100).toFixed(decimals)}%`
}

function formatSignedPercentagePoints(value: number, decimals = 1): string {
  const pp = value * 100
  const sign = pp > 0 ? '+' : ''
  return `${sign}${pp.toFixed(decimals)} 个百分点`
}

function gapTone(value: number): string {
  if (value > 1e-6) return 'text-amber-400 font-medium'
  if (value < -1e-6) return 'text-emerald-400 font-medium'
  return 'text-[var(--gr-text-secondary)]'
}

function findComparisonBlock(
  report: ReportResponse | undefined,
  planId: string,
): HoldingRiskComparisonBlock | null {
  if (!report) return null
  const riskSection = report.sections.find(
    sec => sec.plan_id === planId && sec.kind === 'risk' && sec.section_id === `${planId}:risk`,
  )
  if (!riskSection || riskSection.content.status !== 'ready') return null
  for (const block of riskSection.content.value) {
    if (block.type === 'holding_risk_comparison') {
      return block
    }
  }
  return null
}

function ModelDetailMetric({
  label,
  metric,
  unit,
}: {
  label: string
  metric?: MetricValue<number> | null
  unit: 'variance' | 'percent'
}) {
  return (
    <div className="rounded-lg border border-[var(--gr-border)] p-3.5">
      <dt className="text-xs text-[var(--gr-text-secondary)]">{label}</dt>
      <dd className="mt-1.5 text-lg font-semibold tabular-nums">
        {!metric || metric.status === 'unavailable'
          ? '不可用'
          : unit === 'percent'
            ? `${(metric.value * 100).toFixed(4)}%`
            : `${metric.value.toPrecision(6)}（方差）`}
      </dd>
      {metric && metric.status !== 'ok' && (
        <p className="mt-1.5 text-xs text-[var(--gr-text-secondary)]">{metric.reason}</p>
      )}
    </div>
  )
}

function StockTable({ rows }: { rows: HoldingRiskStockRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[540px] text-left text-sm">
        <thead>
          <tr className="border-b border-[var(--gr-border)] text-xs text-[var(--gr-text-secondary)]">
            <th className="p-2">股票代码</th>
            <th className="p-2">名称</th>
            <th className="p-2 text-right">模型采用的资金权重</th>
            <th className="p-2 text-right">风险贡献份额</th>
            <th className="p-2 text-right">风险份额 − 资金权重</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(row => (
            <tr key={row.instrument_id} className="border-t border-[var(--gr-border)]">
              <td className="p-2 font-mono text-xs">{row.symbol}</td>
              <td className="p-2">{row.name}</td>
              <td className="p-2 text-right tabular-nums">{formatPercent(row.capital_weight)}</td>
              <td className="p-2 text-right tabular-nums">{formatPercent(row.risk_share)}</td>
              <td className={`p-2 text-right tabular-nums ${gapTone(row.risk_share_minus_weight)}`}>
                {formatSignedPercentagePoints(row.risk_share_minus_weight)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function IndustryTable({ rows }: { rows: HoldingRiskIndustryRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[500px] text-left text-sm">
        <thead>
          <tr className="border-b border-[var(--gr-border)] text-xs text-[var(--gr-text-secondary)]">
            <th className="p-2">行业</th>
            <th className="p-2 text-right">模型采用的资金权重</th>
            <th className="p-2 text-right">风险贡献份额</th>
            <th className="p-2 text-right">风险份额 − 资金权重</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(row => (
            <tr key={row.industry_code} className="border-t border-[var(--gr-border)]">
              <td className="p-2">
                {row.industry_name}
                <span className="ml-1.5 font-mono text-xs text-[var(--gr-text-secondary)]">
                  {row.industry_code}
                </span>
              </td>
              <td className="p-2 text-right tabular-nums">{formatPercent(row.capital_weight)}</td>
              <td className="p-2 text-right tabular-nums">{formatPercent(row.risk_share)}</td>
              <td className={`p-2 text-right tabular-nums ${gapTone(row.risk_share_minus_weight)}`}>
                {formatSignedPercentagePoints(row.risk_share_minus_weight)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function HistoryReplaySummary({
  section,
  statsWindow,
}: {
  section: SectionResult<HistorySection>
  statsWindow: { start: string; end: string } | null
}) {
  if (section.status === 'failed') {
    return (
      <div className="mt-4 rounded-lg border border-red-400/30 bg-red-400/10 p-3.5 text-xs text-red-300">
        <p className="font-medium">历史回放计算失败</p>
        <p className="mt-1">{section.error.message}</p>
      </div>
    )
  }
  if (section.status === 'unavailable') {
    return (
      <div className="mt-4 rounded-lg border border-[var(--gr-border)] p-3.5 text-xs text-[var(--gr-text-secondary)]">
        <p className="font-medium text-[var(--gr-text-primary)]">历史回放与基准对照暂不可用</p>
        <p className="mt-1">
          {section.reason}（{section.reason_code}）
        </p>
      </div>
    )
  }

  const history = section.value
  const replay = history.replay
  const drawdown = history.max_drawdown
  const comparison = history.period_comparison ?? null
  const series = replay.status !== 'unavailable' ? replay.value : null
  const lastNav = series && series.nav.length > 0 ? series.nav[series.nav.length - 1] : null
  const lastDate = series && series.dates.length > 0 ? series.dates[series.dates.length - 1] : null

  return (
    <div className="mt-4 rounded-lg border border-[var(--gr-border)] bg-white/[0.02] p-4 space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-xs font-medium uppercase tracking-wide text-[var(--gr-text-secondary)]">
          历史回放、回撤路径与同窗基准对照
        </p>
        <span className="text-xs text-[var(--gr-text-secondary)]">
          {statsWindow ? `统计区间：${statsWindow.start} ～ ${statsWindow.end}` : '统计区间：—'}
          {series ? ` · 建仓起算：${series.build_start}（共 ${series.dates.length} 个交易日收盘）` : ''}
        </span>
      </div>

      <p className="text-xs text-[var(--gr-text-secondary)]">
        这篮子股票的假设历史回放：按输入权重建仓后买入持有、权重自然漂移、税前分红再投资、小数股、现金不计息、未扣交易成本。
        {lastNav !== null && lastDate ? ` 末日净值 ${lastNav.toFixed(4)}（${lastDate}）。` : ''}
      </p>

      {series?.truncated_at && (
        <p role="status" className="rounded-md bg-amber-500/10 p-2.5 text-xs text-amber-400">
          回放截断提示：曲线止于最后可靠收盘 {series.truncated_at}（原因：{series.termination_reason}）。
          {replay.status === 'degraded' ? ` ${replay.reason}` : ''}
        </p>
      )}

      {series && series.unexecuted.length > 0 && (
        <p className="text-xs text-amber-400">
          未成交买入提示：区间结束仍有 {series.unexecuted.length} 笔预留现金因停牌或开盘涨停未能买入。
        </p>
      )}

      {/* 最大回撤路径 */}
      <div className="rounded-md border border-[var(--gr-border)] p-3 text-sm">
        <p className="text-xs font-medium text-[var(--gr-text-secondary)]">最大回撤路径</p>
        {drawdown.status !== 'unavailable' ? (
          <div className="mt-1.5 space-y-1">
            {drawdown.value.value === 0 ? (
              <p className="font-medium">窗口内无回撤</p>
            ) : (
              <p className="leading-relaxed">
                最大回撤{' '}
                <span className="font-semibold tabular-nums">
                  {formatPercent(drawdown.value.value, 2)}
                </span>
                ，峰值日 <span className="font-mono text-xs">{drawdown.value.peak_date}</span>，谷底日{' '}
                <span className="font-mono text-xs">{drawdown.value.trough_date}</span>，
                {drawdown.value.recovery_date ? (
                  <>
                    恢复日 <span className="font-mono text-xs">{drawdown.value.recovery_date}</span>
                  </>
                ) : (
                  <>
                    截至{' '}
                    <span className="font-mono text-xs">
                      {drawdown.window_actual?.end ?? statsWindow?.end ?? drawdown.value.trough_date}
                    </span>{' '}
                    尚未恢复
                  </>
                )}
                ，持续 <span className="font-semibold tabular-nums">{drawdown.value.duration_days}</span>{' '}
                个交易日间隔。
              </p>
            )}
            {drawdown.status === 'degraded' && (
              <p className="text-xs text-amber-400">
                降级说明（{drawdown.reason_code}）：{drawdown.reason}
              </p>
            )}
          </div>
        ) : (
          <p className="mt-1 text-xs text-[var(--gr-text-secondary)]">
            不可用（{drawdown.reason_code}）：{drawdown.reason}
          </p>
        )}
      </div>

      {/* 同期累计收益差 */}
      <div className="rounded-md border border-[var(--gr-border)] p-3 text-sm">
        <p className="text-xs font-medium text-[var(--gr-text-secondary)]">同窗累计收益对照</p>
        {comparison && comparison.status !== 'unavailable' ? (
          <div className="mt-2 space-y-2">
            <dl className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-md border border-[var(--gr-border)] p-2.5">
                <dt className="text-xs text-[var(--gr-text-secondary)]">组合累计简单收益</dt>
                <dd className="mt-1 text-lg font-semibold tabular-nums">
                  {formatPercent(comparison.value.portfolio_simple_return, 2)}
                </dd>
              </div>
              <div className="rounded-md border border-[var(--gr-border)] p-2.5">
                <dt className="text-xs text-[var(--gr-text-secondary)]">
                  基准：{comparison.value.benchmark_name}（{comparison.value.benchmark_symbol}）
                </dt>
                <dd className="mt-1 text-lg font-semibold tabular-nums">
                  {formatPercent(comparison.value.benchmark_simple_return, 2)}
                </dd>
              </div>
              <div className="rounded-md border border-[var(--gr-border)] p-2.5">
                <dt className="text-xs text-[var(--gr-text-secondary)]">同期收益差（组合 − 基准）</dt>
                <dd
                  className={`mt-1 text-lg font-semibold tabular-nums ${gapTone(comparison.value.return_difference)}`}
                >
                  {formatSignedPercentagePoints(comparison.value.return_difference, 2)}
                </dd>
              </div>
            </dl>
            <p className="text-xs text-[var(--gr-text-secondary)]">
              实际首末收盘：{comparison.window_actual?.start ?? '—'} ～{' '}
              {comparison.window_actual?.end ?? '—'} · 匹配交易日收益数：{comparison.sample_count ?? 0}
            </p>
          </div>
        ) : (
          <p className="mt-1 text-xs text-[var(--gr-text-secondary)]">
            {comparison && comparison.status === 'unavailable'
              ? `暂不可用（${comparison.reason_code}）：${comparison.reason}`
              : '该历史快照未包含同期收益对照字段。'}
          </p>
        )}
      </div>
    </div>
  )
}

function PlanHoldingReportCard({
  plan,
  comparison,
  quality,
  asOfDate,
  statsWindow,
}: {
  plan: PlanResult
  comparison: HoldingRiskComparisonBlock | null
  quality?: PlanDataQuality
  asOfDate: string
  statsWindow: { start: string; end: string } | null
}) {
  const risk = plan.section_b.status === 'ready' ? plan.section_b.value : null
  const coverage = risk?.model_coverage
  const stockMetric = comparison?.stocks
  const industryMetric = comparison?.industries
  const hasStocks = stockMetric !== undefined && stockMetric.status !== 'unavailable'
  const stockRows = hasStocks ? stockMetric.value : []
  const topStock = stockRows[0]

  return (
    <section className={PANEL} aria-label={`${plan.label || plan.plan_id}仓位与风险报告`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-lg font-semibold">{plan.label || plan.plan_id}</h3>
        <span className="text-xs text-[var(--gr-text-secondary)]">
          诊断日：{asOfDate} · 模型日：{comparison?.model_date || risk?.model_date || '—'} ·
          输入解析覆盖：{(plan.input.calculation_coverage_ratio * 100).toFixed(2)}%
        </span>
      </div>

      {plan.error && (
        <p role="alert" className="mt-3 text-sm text-red-400">
          {plan.error.message}
        </p>
      )}

      {/* 首屏核心发现 + 原始两列 */}
      {comparison ? (
        <div className="mt-4 space-y-4">
          {hasStocks && topStock ? (
            <div className="rounded-lg border border-[var(--gr-border)] bg-white/[0.02] p-4">
              <p className="text-xs font-medium uppercase tracking-wide text-[var(--gr-text-secondary)]">
                核心发现（仓位 vs 模型风险贡献）
              </p>
              {comparison.headline && (
                <p className="mt-2 text-base font-medium leading-relaxed">{comparison.headline}</p>
              )}
              <dl className="mt-4 grid gap-3 sm:grid-cols-3">
                <div className="rounded-md border border-[var(--gr-border)] p-3">
                  <dt className="text-xs text-[var(--gr-text-secondary)]">
                    {topStock.name} · 模型采用的资金权重
                  </dt>
                  <dd className="mt-1 text-xl font-semibold tabular-nums">
                    {formatPercent(topStock.capital_weight)}
                  </dd>
                </div>
                <div className="rounded-md border border-[var(--gr-border)] p-3">
                  <dt className="text-xs text-[var(--gr-text-secondary)]">
                    {topStock.name} · 风险贡献份额
                  </dt>
                  <dd className="mt-1 text-xl font-semibold tabular-nums">
                    {formatPercent(topStock.risk_share)}
                  </dd>
                </div>
                <div className="rounded-md border border-[var(--gr-border)] p-3">
                  <dt className="text-xs text-[var(--gr-text-secondary)]">风险份额 − 资金权重</dt>
                  <dd
                    className={`mt-1 text-xl font-semibold tabular-nums ${gapTone(topStock.risk_share_minus_weight)}`}
                  >
                    {formatSignedPercentagePoints(topStock.risk_share_minus_weight)}
                  </dd>
                </div>
              </dl>
              {stockMetric.status === 'degraded' && (
                <p className="mt-3 text-xs text-amber-400">
                  降级说明（{stockMetric.reason_code}）：{stockMetric.reason}
                </p>
              )}
            </div>
          ) : (
            <div
              role="status"
              className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-300"
            >
              <p className="font-medium">仓位与风险贡献对照暂不可用</p>
              <p className="mt-1 text-xs">
                {stockMetric && stockMetric.status === 'unavailable'
                  ? `${stockMetric.reason}（${stockMetric.reason_code}）`
                  : '缺少完整的模型风险贡献数据。'}
              </p>
            </div>
          )}

          {/* 适用范围与局限披露 */}
          <div className="space-y-1.5 text-xs text-[var(--gr-text-secondary)]">
            <p>
              仓位分母：本次输入的沪深 A 股股票组合；模型：{comparison.model_id || '未取得'} · run：
              {comparison.model_run_id || '—'}
              {coverage
                ? ` · 模型持仓覆盖：${coverage.covered_count}/${coverage.total_count}`
                : ''}
            </p>
            {comparison.calibrated === false && (
              <p className="rounded-md bg-amber-500/10 p-2.5 text-amber-400">
                未校准提示（calibrated=false）：当前风险份额基于已准入的供应商单日风险模型截面计算，全区间校准尚未完成，仅供仓位与风险结构核对。
              </p>
            )}
            {comparison.quantized_zero_count > 0 && (
              <p className="rounded-md border border-[var(--gr-border)] p-2.5">
                8 位量化归零披露：另有 {comparison.quantized_zero_count} 只极小正权重证券（合计原始份额{' '}
                {comparison.quantized_zero_weight}）按模型 8 位精度量化为 0，未纳入对照且不虚构风险份额。
              </p>
            )}
            {plan.input.unresolved_weight > 0 && (
              <p className="text-amber-400">
                未识别输入份额 {(plan.input.unresolved_weight * 100).toFixed(4)}%，不会以已识别子集代替完整组合输出风险对照。
              </p>
            )}
          </div>

          {/* 展开查明细：逐股表 + 行业表 */}
          {hasStocks && (
            <details className="rounded-lg border border-[var(--gr-border)] p-3.5" open={stockRows.length <= 10}>
              <summary className="cursor-pointer text-sm font-medium">
                展开查看全部逐股与行业仓位风险明细（共 {stockRows.length} 只有效股票）
              </summary>
              <div className="mt-4 space-y-5">
                <div>
                  <h4 className="mb-2 text-xs font-medium text-[var(--gr-text-secondary)]">
                    逐股仓位与风险贡献对照（按未舍入差值降序。差值为负表示风险贡献低于资金权重；仅当风险贡献份额本身为负时，才表示该股在当前模型下抵消了部分组合风险）
                  </h4>
                  <StockTable rows={stockRows} />
                </div>

                <div>
                  <h4 className="mb-2 text-xs font-medium text-[var(--gr-text-secondary)]">
                    行业仓位与风险贡献对照（行业内先分别加总资金权重与风险贡献份额再作差；差值为负表示该行业风险贡献低于资金权重）
                  </h4>
                  {industryMetric && industryMetric.status !== 'unavailable' ? (
                    <>
                      <IndustryTable rows={industryMetric.value} />
                      {industryMetric.status === 'degraded' && (
                        <p className="mt-2 text-xs text-amber-400">
                          行业对照降级（{industryMetric.reason_code}）：{industryMetric.reason}
                        </p>
                      )}
                    </>
                  ) : (
                    <p className="rounded-md border border-[var(--gr-border)] p-3 text-xs text-[var(--gr-text-secondary)]">
                      行业对照不可用：
                      {industryMetric && industryMetric.status === 'unavailable'
                        ? `${industryMetric.reason}（${industryMetric.reason_code}）`
                        : '缺少行业分类数据。'}
                    </p>
                  )}
                </div>
              </div>
            </details>
          )}
        </div>
      ) : (
        <p className="mt-3 text-sm text-[var(--gr-text-secondary)]">正在读取结构化报告明细…</p>
      )}

      {/* 历史回放、回撤路径与基准对照 */}
      <HistoryReplaySummary section={plan.section_c} statsWindow={statsWindow} />

      {/* 模型明细（收拢原三个波动/方差数字 + 缺口 + 持仓解析 + 数据质量） */}
      <details className="mt-4 rounded-lg border border-[var(--gr-border)] p-3.5 text-sm">
        <summary className="cursor-pointer font-medium">
          模型波动明细、持仓解析与数据质量（{quality?.issues.length ?? 0} 条提示）
        </summary>
        <div className="mt-4 space-y-4">
          <dl className="grid gap-3 md:grid-cols-3">
            <ModelDetailMetric label="组合年化方差" metric={risk?.annual_variance} unit="variance" />
            <ModelDetailMetric
              label="年化预测波动率"
              metric={risk?.volatility.by_method.forward}
              unit="percent"
            />
            <ModelDetailMetric
              label="单日预测波动率"
              metric={risk?.daily_prediction_volatility}
              unit="percent"
            />
          </dl>

          {!!coverage?.missing.length && (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <caption className="mb-1.5 text-left font-medium">必要风险输入缺口</caption>
                <thead>
                  <tr className="border-b border-[var(--gr-border)] text-[var(--gr-text-secondary)]">
                    <th className="p-2">证券</th>
                    <th className="p-2">权重</th>
                    <th className="p-2">原因</th>
                  </tr>
                </thead>
                <tbody>
                  {coverage.missing.map((item, index) => (
                    <tr key={`${item.symbol}-${index}`} className="border-t border-[var(--gr-border)]">
                      <td className="p-2 font-mono">{item.symbol}</td>
                      <td className="p-2 tabular-nums">
                        {Number(item.weight).toLocaleString('zh-CN', {
                          style: 'percent',
                          maximumFractionDigits: 4,
                        })}
                      </td>
                      <td className="p-2">{item.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <caption className="mb-1.5 text-left font-medium">服务端持仓解析与权重</caption>
              <thead>
                <tr className="border-b border-[var(--gr-border)] text-[var(--gr-text-secondary)]">
                  <th className="p-2">输入代码</th>
                  <th className="p-2">原始权重</th>
                  <th className="p-2">解析标的</th>
                  <th className="p-2">状态</th>
                </tr>
              </thead>
              <tbody>
                {plan.input.holdings.map(row => (
                  <tr key={row.input_index} className="border-t border-[var(--gr-border)]">
                    <td className="p-2 font-mono">{row.input_symbol}</td>
                    <td className="p-2 tabular-nums">{row.input_weight ?? '等权'}</td>
                    <td className="p-2">{row.name || row.normalized_symbol}</td>
                    <td className="p-2">{row.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {quality && quality.issues.length > 0 && (
            <div className="space-y-1 text-xs text-[var(--gr-text-secondary)]">
              <p className="font-medium text-[var(--gr-text-primary)]">本方案数据质量提示</p>
              <ul className="list-disc space-y-1 pl-5">
                {quality.issues.map((issue, idx) => (
                  <li key={`${issue.code}-${idx}`}>
                    <span className="font-mono">{issue.code}</span>：{issue.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </details>
    </section>
  )
}

export function HoldingsReport({
  result,
  report,
  dataQuality,
}: {
  result: DiagnosisResult
  report?: ReportResponse
  dataQuality?: DataQualityReport
}) {
  const qualityPlans = dataQuality?.plans ?? result.data_quality.plans
  const qualityByPlan = new Map(qualityPlans.map(item => [item.plan_id, item]))
  const disclosures = report?.disclosures ?? result.disclosures

  return (
    <div className="space-y-5">
      {result.plans.map(plan => (
        <PlanHoldingReportCard
          key={plan.plan_id}
          plan={plan}
          comparison={findComparisonBlock(report, plan.plan_id)}
          quality={qualityByPlan.get(plan.plan_id)}
          asOfDate={result.as_of_date}
          statsWindow={result.options.stats_window}
        />
      ))}

      <section className={PANEL}>
        <h3 className="font-semibold">适用范围与数据局限说明</h3>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-sm text-[var(--gr-text-secondary)]">
          {disclosures.map((text, index) => (
            <li key={index}>{text}</li>
          ))}
        </ul>
      </section>
    </div>
  )
}
