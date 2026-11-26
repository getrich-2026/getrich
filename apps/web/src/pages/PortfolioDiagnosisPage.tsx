import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useFieldArray, useForm, type Control, type UseFormRegister, type FieldErrors } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Plus, Trash2, Copy, Upload, RefreshCw, Download } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  createSnapshot,
  diagnosisError,
  getDiagnosisDataQuality,
  getDiagnosisReport,
  getDiagnosisResult,
  getPublishedOptions,
} from '@/api/diagnosis'
import { loginWithPassword } from '@/api/auth'
import { HoldingsReport } from '@/components/diagnosis/HoldingsReport'
import { buildSnapshotPlans, parsePortfolioText, validatePortfolioDrafts, type PortfolioDraft } from '@/lib/portfolio-import'
import type { DiagnosisResult, ReportResponse, SnapshotRequest } from '@/types/diagnosis'

const editorSchema = z.object({
  plans: z.array(z.object({
    plan_id: z.string().min(1),
    label: z.string().max(32, '方案名称最多 32 字符。'),
    holdings: z.array(z.object({ symbol: z.string(), weight: z.string() })),
  })),
}).superRefine((data, context) => {
  for (const issue of validatePortfolioDrafts(data.plans)) {
    context.addIssue({ code: 'custom', path: issue.path, message: issue.message })
  }
})
type EditorValues = z.infer<typeof editorSchema>

const PANEL = 'rounded-xl border border-[var(--gr-border)] bg-[var(--gr-bg-card)] p-5'
const emptyPlan = (): PortfolioDraft => ({ plan_id: `plan_${crypto.randomUUID().replaceAll('-', '')}`, label: '', holdings: [{ symbol: '', weight: '' }] })
const regressionHoldings = [
  { symbol: '600519.SH', weight: '40' },
  { symbol: '600036.SH', weight: '35' },
  { symbol: '000333.SZ', weight: '25' },
]
const metricLabels: Record<string, string> = {
  annual_variance: '年化方差',
  volatility: '年化预测波动率',
  daily_prediction_volatility: '单日预测波动率',
  risk_contribution: '逐股风险贡献',
  risk_contribution_ratio: '逐股风险贡献份额',
  marginal_risk_contribution: '边际风险贡献',
  l3_effective_count: '风险有效持仓数（L3）',
  l4_effective_count: '风险源方差集中度（L4）',
  l4_market_source_share: '市场源占比',
  l4_largest_source: '最大风险源占比',
  style_exposure: '风格暴露',
  model_correlation: '模型相关性',
}

function errorMessage(error: unknown): string {
  return diagnosisError(error)?.message || (error instanceof Error ? error.message : '请求失败，请稍后重试。')
}

function PlanEditor({ index, control, register, errors, busy, onRemove, onCopy, removable, copyable }: {
  index: number; control: Control<EditorValues>; register: UseFormRegister<EditorValues>; errors: FieldErrors<EditorValues>
  busy: boolean; onRemove: () => void; onCopy: () => void; removable: boolean; copyable: boolean
}) {
  const rows = useFieldArray({ control, name: `plans.${index}.holdings` })
  const [importError, setImportError] = useState<string | null>(null)
  const [importing, setImporting] = useState(false)
  const planError = errors.plans?.[index]
  const holdingsError = planError?.holdings?.root?.message || planError?.holdings?.message
  async function importFile(file: File) {
    setImportError(null)
    if (!/\.(csv|tsv|txt)$/i.test(file.name)) { setImportError('请另存为 UTF-8 CSV、TSV 或 TXT 后导入。'); return }
    if (file.size > 1024 * 1024) { setImportError('文件超过 1 MB，请保留最多 100 行持仓。'); return }
    setImporting(true)
    try { rows.replace(parsePortfolioText(await file.text())) }
    catch (error) { setImportError(errorMessage(error)) }
    finally { setImporting(false) }
  }
  return <fieldset className={PANEL} disabled={busy || importing}>
    <legend className="px-2 font-semibold">方案 {index + 1}</legend>
    <div className="mb-4 flex flex-wrap items-center gap-2">
      <Input {...register(`plans.${index}.label`)} maxLength={32} placeholder={`方案 ${index + 1}（可选名称）`} aria-label={`方案 ${index + 1}名称`} className="max-w-xs" />
      <Button type="button" variant="outline" disabled={!copyable} onClick={onCopy}><Copy />复制后调权</Button>
      <Button type="button" variant="ghost" disabled={!removable} onClick={onRemove}><Trash2 />删除方案</Button>
      <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border border-[var(--gr-border)] px-3 py-2 text-sm">
        <Upload size={16} />{importing ? '正在解析文件…' : '导入 CSV / TSV'}
        <input type="file" accept=".csv,.tsv,.txt,text/csv,text/tab-separated-values,text/plain" className="sr-only" aria-label={`导入方案 ${index + 1}持仓文件`} onChange={event => { const input = event.currentTarget; const file = input.files?.[0]; if (file) void importFile(file); input.value = '' }} />
      </label>
    </div>
    <p className="mb-3 text-xs text-[var(--gr-text-secondary)]">权重可填 40、35、25 等相对份额，或统一填写 40%、35%、25%；无需合计 100%。全部留空时由服务端去重后等权。文件只在浏览器解析。Excel 文件请先另存为 UTF-8 CSV 或 TSV。</p>
    {importError && <p role="alert" className="mb-3 text-sm text-red-400">{importError}</p>}
    {planError?.label && <p role="alert" className="mb-3 text-sm text-red-400">{planError.label.message}</p>}
    <div className="max-h-96 overflow-auto"><table className="w-full text-left text-sm"><thead className="sticky top-0 bg-[var(--gr-bg-card)]"><tr><th className="p-2">行</th><th className="p-2">股票代码</th><th className="p-2">权重</th><th className="p-2"><span className="sr-only">操作</span></th></tr></thead><tbody>{rows.fields.map((row, rowIndex) => <tr key={row.id} className="border-t border-[var(--gr-border)] align-top">
      <td className="p-2 pt-4 text-[var(--gr-text-secondary)]">{rowIndex + 1}</td>
      <td className="p-2"><Input {...register(`plans.${index}.holdings.${rowIndex}.symbol`)} placeholder="如 600519.SH" autoComplete="off" maxLength={64} aria-label={`方案 ${index + 1}第 ${rowIndex + 1}行股票代码`} aria-invalid={!!planError?.holdings?.[rowIndex]?.symbol} />{planError?.holdings?.[rowIndex]?.symbol && <p className="mt-1 text-xs text-red-400">{planError.holdings[rowIndex]?.symbol?.message}</p>}</td>
      <td className="p-2"><Input {...register(`plans.${index}.holdings.${rowIndex}.weight`)} placeholder="如 40 或 40%" autoComplete="off" inputMode="decimal" maxLength={80} aria-label={`方案 ${index + 1}第 ${rowIndex + 1}行权重`} aria-invalid={!!planError?.holdings?.[rowIndex]?.weight} />{planError?.holdings?.[rowIndex]?.weight && <p className="mt-1 text-xs text-red-400">{planError.holdings[rowIndex]?.weight?.message}</p>}</td>
      <td className="p-2"><Button type="button" variant="ghost" size="icon" aria-label={`删除方案 ${index + 1}第 ${rowIndex + 1}行`} disabled={rows.fields.length <= 1} onClick={() => rows.remove(rowIndex)}><Trash2 /></Button></td>
    </tr>)}</tbody></table></div>
    <div className="mt-3 flex items-center gap-3"><Button type="button" variant="outline" disabled={rows.fields.length >= 100} onClick={() => rows.append({ symbol: '', weight: '' })}><Plus />新增股票</Button><span className="text-xs text-[var(--gr-text-secondary)]">{rows.fields.length} / 100 行（含重复与零权重）</span></div>
    {holdingsError && <p role="alert" className="mt-3 text-sm text-red-400">{holdingsError}</p>}
  </fieldset>
}

function DiagnosisEditor({ sessionId, sessionSignal }: { sessionId: string; sessionSignal: AbortSignal }) {
  const [snapshotId, setSnapshotId] = useState<string | null>(null)
  const [submitted, setSubmitted] = useState<{ body: SnapshotRequest; key: string } | null>(null)
  const form = useForm<EditorValues>({ resolver: zodResolver(editorSchema), defaultValues: { plans: [{ plan_id: 'plan_1', label: '', holdings: [{ symbol: '', weight: '' }] }] } })
  const plans = useFieldArray({ control: form.control, name: 'plans' })
  const published = useQuery({ queryKey: ['diagnosis', sessionId, 'published-options'], queryFn: ({ signal }) => getPublishedOptions(signal), retry: false, staleTime: 0, refetchOnWindowFocus: true })
  const mutation = useMutation({
    mutationFn: ({ body, key }: { body: SnapshotRequest; key: string }) => createSnapshot(body, key, sessionSignal),
    retry: false,
    gcTime: 0,
    onSuccess: data => { if (!sessionSignal.aborted) { setSnapshotId(data.snapshot_id) } },
  })
  const result = useQuery({
    queryKey: ['diagnosis', sessionId, 'result', snapshotId],
    queryFn: ({ signal }) => getDiagnosisResult(snapshotId!, signal),
    enabled: snapshotId !== null,
    retry: false,
    gcTime: 0,
    refetchInterval: query => query.state.data?.run_status === 'pending' || query.state.data?.run_status === 'running' ? 1000 : false,
  })
  const complete: DiagnosisResult | undefined = result.data && 'comparison' in result.data ? result.data : undefined
  const report = useQuery({
    queryKey: ['diagnosis', sessionId, 'report', snapshotId, 'retail', 'holdings'],
    queryFn: ({ signal }) => getDiagnosisReport(snapshotId!, 'retail', signal, 'holdings'),
    enabled: !!complete && snapshotId !== null,
    retry: false,
    gcTime: 0,
    refetchInterval: query => query.state.data?.run_status === 'pending' || query.state.data?.run_status === 'running' ? 1000 : false,
  })
  const quality = useQuery({
    queryKey: ['diagnosis', sessionId, 'data-quality', snapshotId],
    queryFn: ({ signal }) => getDiagnosisDataQuality(snapshotId!, signal),
    enabled: !!complete && snapshotId !== null,
    retry: false,
    gcTime: 0,
  })
  const readyReport: ReportResponse | undefined = report.data && 'sections' in report.data ? report.data : undefined
  const readyQuality = quality.data && 'data_quality' in quality.data ? quality.data.data_quality : undefined
  const busy = mutation.isPending || result.isFetching && !complete || result.data?.run_status === 'pending' || result.data?.run_status === 'running'
  function submit(values: EditorValues) {
    const body: SnapshotRequest = { plans: buildSnapshotPlans(values.plans), ...(published.data ? { as_of_date: published.data.as_of_date } : {}) }
    const submission = { body, key: crypto.randomUUID() }
    setSubmitted(submission)
    form.reset(values)
    setSnapshotId(null)
    mutation.mutate(submission)
  }
  function template() {
    const link = document.createElement('a')
    const url = URL.createObjectURL(new Blob(['\uFEFF股票代码,权重\n600519.SH,40\n600036.SH,35\n000333.SZ,25\n'], { type: 'text/csv;charset=utf-8' }))
    link.href = url; link.download = '持仓导入模板.csv'; link.click(); URL.revokeObjectURL(url)
  }
  const backendError = diagnosisError(mutation.error)
  return <div className="space-y-6">
    <section className={PANEL} aria-label="当前已发布数据">
      <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-semibold">当前可用数据</h2><Button type="button" variant="ghost" size="sm" onClick={() => void published.refetch()} disabled={published.isFetching}><RefreshCw />刷新</Button></div>
      {published.isLoading && <p className="mt-2 text-sm">正在读取发布信息…</p>}
      {published.isError && <p role="alert" className="mt-2 text-sm text-amber-400">{errorMessage(published.error)}</p>}
      {published.data && <div className="mt-2 space-y-1 break-all text-sm text-[var(--gr-text-secondary)]"><p>数据日期：{published.data.as_of_date} · 版本：{published.data.data_version_id}</p><p>已准入指标：{published.data.declared_metrics.map(metric => metricLabels[metric] || metric).join('、') || '暂无'}</p>{published.data.publication_scope && <><p>模型：{published.data.publication_scope.model} · run：{published.data.publication_scope.run_id}</p><p>{published.data.publication_scope.scope_type === 'security_universe' ? `已验收证券范围：${published.data.publication_scope.security_ids?.length ?? '未披露'} 只；范围内可自由组合和调权。` : '此版本限定已登记组合，持仓或权重超出原范围时模型风险不可用。'} · calibrated={String(published.data.publication_scope.calibrated)}</p></>}</div>}
    </section>
    <form onSubmit={form.handleSubmit(submit)} className="space-y-5" noValidate>
      <div className="flex flex-wrap gap-2"><Button type="button" variant="outline" onClick={() => plans.append(emptyPlan())} disabled={busy || plans.fields.length >= 5}><Plus />新增方案</Button><Button type="button" variant="outline" onClick={template}><Download />下载导入模板</Button><Button type="button" variant="ghost" disabled={busy} onClick={() => { plans.replace([{ plan_id: 'regression', label: '三股回归样本', holdings: regressionHoldings.map(row => ({ ...row })) }]); form.clearErrors() }}>载入三股回归样本</Button></div>
      {plans.fields.map((plan, index) => <PlanEditor key={plan.id} index={index} control={form.control} register={form.register} errors={form.formState.errors} busy={busy} removable={plans.fields.length > 1} copyable={plans.fields.length < 5} onRemove={() => plans.remove(index)} onCopy={() => { const original = form.getValues(`plans.${index}`); plans.append({ ...original, plan_id: `plan_${crypto.randomUUID().replaceAll('-', '')}`, label: original.label ? `${original.label.slice(0, 27)} 副本` : '权重方案副本', holdings: original.holdings.map(row => ({ ...row })) }) }} />)}
      <div className="sticky bottom-0 z-10 flex flex-wrap items-center gap-3 rounded-xl border border-[var(--gr-border)] bg-[var(--gr-bg-card)] p-4"><Button type="submit" disabled={busy || !published.data || published.isError}>{busy ? '正在计算…' : snapshotId ? '按当前完整持仓再次计算' : '计算组合风险'}</Button><span className="text-xs text-[var(--gr-text-secondary)]">修改后重新提交会创建新结果；查看两套权重请复制方案后一起提交。</span></div>
      {mutation.isError && <div role="alert" className="rounded-lg border border-red-400/40 p-4 text-sm text-red-400"><p>{errorMessage(mutation.error)}</p>{backendError?.issues.map((issue, index) => <p key={`${issue.path}-${index}`} className="mt-1">{issue.path}：{issue.message}</p>)}{backendError?.retryable && submitted && <Button type="button" className="mt-3" variant="outline" onClick={() => mutation.mutate(submitted)}>重试上次提交</Button>}</div>}
    </form>
    {!published.data && !published.isLoading && <p className="text-sm text-[var(--gr-text-secondary)]">当前没有可用发布，暂不能计算。可先编辑或导入持仓，数据恢复后再提交。</p>}
    {result.isError && <p role="alert" className="rounded-lg border border-red-400/40 p-4 text-sm text-red-400">读取结果失败：{errorMessage(result.error)}</p>}
    {snapshotId && !complete && !result.isError && <p role="status" className="text-sm">正在取得计算结果…</p>}
    {complete && form.formState.isDirty && <p role="status" className="rounded-lg bg-amber-500/10 p-3 text-sm text-amber-400">持仓或权重已修改。下方为上次提交的结果，请点击“按当前完整持仓再次计算”更新。</p>}
    {complete && !result.isError && <div className="space-y-5" aria-live="polite">
      <section className={PANEL}>
        <h2 className="text-lg font-semibold">诊断报告</h2>
        <div className="mt-3 space-y-1 break-all text-sm text-[var(--gr-text-secondary)]">
          <p>实际数据日期：{complete.as_of_date} · 发布版本：{complete.data_fingerprint}</p>
          <p>口径：{complete.spec_version} · 快照：{complete.snapshot_id}</p>
          <p>发布状态：{complete.publication?.status || '未披露'}；原结果可重算：{complete.publication?.recomputable ? '是' : '否'}</p>
        </div>
        {complete.publication?.status === 'invalidated' && <p role="alert" className="mt-3 text-sm text-amber-400">此版本已失效，以下为已保存的原结果。原版本不可重算，请用当前持仓提交新的诊断。</p>}
        {report.isError && <p role="alert" className="mt-3 text-sm text-red-400">读取报告失败：{errorMessage(report.error)}</p>}
      </section>
      <HoldingsReport result={complete} report={readyReport} dataQuality={readyQuality} />
    </div>}
  </div>
}

const loginSchema = z.object({
  email: z.email('请输入账号邮箱。').max(255, '邮箱最多 255 字符。'),
  password: z.string().min(1, '请输入密码。').max(128, '密码最多 128 字符。'),
})
type LoginValues = z.infer<typeof loginSchema>

export default function PortfolioDiagnosisPage() {
  const queryClient = useQueryClient()
  const [session, setSession] = useState(() => ({ id: crypto.randomUUID(), controller: new AbortController() }))
  const [identity, setIdentity] = useState<string | null>(() => localStorage.getItem('token') ? '已携带登录凭证' : null)
  const [loginError, setLoginError] = useState<string | null>(null)
  const credentials = useForm<LoginValues>({ resolver: zodResolver(loginSchema), defaultValues: { email: '', password: '' } })

  useEffect(() => {
    // 其他标签页切换身份时重建页面，避免旧凭证的持仓或响应留在当前标签页。
    const synchronizeIdentity = (event: StorageEvent) => {
      if (event.key === null || event.key === 'token' && event.oldValue !== event.newValue) window.location.reload()
    }
    window.addEventListener('storage', synchronizeIdentity)
    return () => window.removeEventListener('storage', synchronizeIdentity)
  }, [])

  function clearSession() {
    session.controller.abort()
    // clear 同时取消查询和移除所有缓存；重挂载编辑器清除持仓及私有本地状态。
    queryClient.clear()
    localStorage.removeItem('token')
    setIdentity(null)
    setSession({ id: crypto.randomUUID(), controller: new AbortController() })
    setLoginError(null)
  }

  const login = useMutation({
    mutationFn: loginWithPassword,
    retry: false,
    gcTime: 0,
    onSuccess: data => {
      clearSession()
      localStorage.setItem('token', data.access_token)
      setIdentity(data.user.name || data.user.email)
      credentials.reset()
    },
    onError: error => setLoginError(errorMessage(error)),
    onSettled: () => { credentials.resetField('password'); login.reset() },
  })

  function submitLogin(values: LoginValues) {
    clearSession()
    login.mutate(values)
    credentials.resetField('password')
  }

  return <div className="mx-auto max-w-6xl space-y-6 px-5 py-8 text-[var(--gr-text-primary)] md:px-8">
    <header><h1 className="text-2xl font-semibold">组合风险诊断</h1><p className="mt-2 text-sm text-[var(--gr-text-secondary)]">导入或编辑沪深 A 股和权重。每次计算提交完整组合；最多 5 个方案，各自独立诊断并共用同一数据版本。</p></header>
    <section className={PANEL} aria-label="诊断账号">
      {identity ? <div className="flex flex-wrap items-center justify-between gap-3"><p className="text-sm">当前账号：{identity}。报告归属和访问权限由服务端验证。</p><Button type="button" variant="outline" onClick={() => { clearSession(); credentials.reset() }}>退出／切换账号</Button></div> : <>
        <h2 className="font-semibold">使用既有账号登录</h2>
        <p className="mt-2 text-sm text-[var(--gr-text-secondary)]">{import.meta.env.VITE_DEMO_USER_ID ? '当前为开发联调身份。' : '当前为匿名模式，结果不属于个人账户。'}登录后提交的诊断归属当前账号。登录或切换账号会清空本页持仓和结果。</p>
        <form onSubmit={credentials.handleSubmit(submitLogin)} className="mt-4 flex flex-wrap items-start gap-3" noValidate>
          <div className="min-w-56 flex-1"><label className="mb-1 block text-sm" htmlFor="diagnosis-login-email">邮箱</label><Input id="diagnosis-login-email" type="email" autoComplete="username" disabled={login.isPending} {...credentials.register('email')} aria-invalid={!!credentials.formState.errors.email} />{credentials.formState.errors.email && <p className="mt-1 text-xs text-red-400">{credentials.formState.errors.email.message}</p>}</div>
          <div className="min-w-56 flex-1"><label className="mb-1 block text-sm" htmlFor="diagnosis-login-password">密码</label><Input id="diagnosis-login-password" type="password" autoComplete="current-password" disabled={login.isPending} {...credentials.register('password')} aria-invalid={!!credentials.formState.errors.password} />{credentials.formState.errors.password && <p className="mt-1 text-xs text-red-400">{credentials.formState.errors.password.message}</p>}</div>
          <Button type="submit" className="mt-6" disabled={login.isPending}>{login.isPending ? '正在登录…' : '登录'}</Button>
        </form>
        {loginError && <p role="alert" className="mt-3 text-sm text-red-400">登录失败：{loginError}</p>}
      </>}
    </section>
    {login.isPending ? <p role="status" className="text-sm">正在切换账号，原持仓和结果已清空…</p> : <DiagnosisEditor key={session.id} sessionId={session.id} sessionSignal={session.controller.signal} />}
  </div>
}
