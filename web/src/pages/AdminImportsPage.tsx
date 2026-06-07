import { useMemo, useState, type ReactNode } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  CheckCircle2,
  Database,
  Download,
  FileUp,
  RotateCcw,
  Save,
  Upload,
} from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import {
  commitAdminImport,
  getAdminImportHistory,
  previewAdminImport,
  upsertAdminStrategy,
} from '@/api/adminImports'
import { strategyImportSchema, type StrategyImportFormValues } from '@/lib/importSchemas'
import type {
  ImportMode,
  ImportPreviewData,
  ImportType,
  ReturnCalcMethod,
  StrategyUpsertBody,
} from '@/types/adminImport'

const strategyDefaults: StrategyImportFormValues = {
  strategy_code: 'STR_FUT_001',
  name: '',
  strategy_type: 'manual',
  summary: '',
  description: '',
  detail_html: '',
  category_id: '',
  asset_class: 'future',
  market: 'cn',
  risk_level: 'medium',
  run_status: 'paper',
  pub_status: 'draft',
  author_id: '',
  cover_image: '',
  subscription_monthly: '0',
  subscription_yearly: '0',
  backtest_start: '',
  backtest_end: '',
}

const templateLinks: Record<ImportType, string> = {
  strategy_daily_returns: '/templates/strategy_daily_returns_template.csv',
  strategy_signals: '/templates/strategy_signals_template.csv',
}

export default function AdminImportsPage() {
  const [importType, setImportType] = useState<ImportType>('strategy_daily_returns')
  const [mode, setMode] = useState<ImportMode>('upsert')
  const [returnCalcMethod, setReturnCalcMethod] = useState<ReturnCalcMethod>('compound')
  const [csvFile, setCsvFile] = useState<File | null>(null)
  const [strategyCodeForCsv, setStrategyCodeForCsv] = useState('STR_FUT_001')
  const [initialNav, setInitialNav] = useState('1')
  const [previewData, setPreviewData] = useState<ImportPreviewData | null>(null)

  const strategyForm = useForm<StrategyImportFormValues>({
    resolver: zodResolver(strategyImportSchema),
    defaultValues: strategyDefaults,
  })

  const strategyMutation = useMutation({
    mutationFn: (body: StrategyUpsertBody) => upsertAdminStrategy(body),
  })

  const previewMutation = useMutation({
    mutationFn: previewAdminImport,
    onSuccess: (response) => {
      setPreviewData(response.data)
    },
  })

  const commitMutation = useMutation({
    mutationFn: commitAdminImport,
    onSuccess: () => {
      void historyQuery.refetch()
    },
  })

  const historyQuery = useQuery({
    queryKey: ['admin-import-history'],
    queryFn: getAdminImportHistory,
    retry: false,
  })

  const previewColumns = useMemo(() => {
    if (!previewData?.preview_rows.length) {
      return []
    }
    return Object.keys(previewData.preview_rows[0]).slice(0, 8)
  }, [previewData])

  const onSaveStrategy = (values: StrategyImportFormValues) => {
    strategyMutation.mutate({
      ...values,
      summary: optionalText(values.summary),
      description: optionalText(values.description),
      detail_html: optionalText(values.detail_html),
      category_id: optionalText(values.category_id),
      cover_image: optionalText(values.cover_image),
      backtest_start: optionalText(values.backtest_start),
      backtest_end: optionalText(values.backtest_end),
    })
  }

  const onPreview = async () => {
    if (!csvFile) {
      return
    }
    const csvText = await csvFile.text()
    previewMutation.mutate({
      import_type: importType,
      csv_text: csvText,
      file_name: csvFile.name,
      strategy_code: optionalText(strategyCodeForCsv),
      mode,
      return_calc_method: returnCalcMethod,
      initial_nav: Number(initialNav) || 1,
      trading_days_per_year: 252,
      risk_free_rate: 0,
    })
  }

  const canCommit = previewData?.status === 'validated' && !commitMutation.isPending

  return (
    <div className="mx-auto max-w-[1280px] px-6 py-6">
      <div className="mb-5 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold" style={{ color: 'var(--gr-text)' }}>
            策略与信号导入
          </h1>
          <p className="mt-1 text-sm" style={{ color: 'var(--gr-text-secondary)' }}>
            后台导入入口，所有写入先预检再提交。
          </p>
        </div>
        <Button variant="outline" onClick={() => historyQuery.refetch()}>
          <RotateCcw />
          刷新
        </Button>
      </div>

      <div className="grid gap-5 xl:grid-cols-[420px_1fr]">
        <section className="rounded-lg bg-white p-5 card-shadow">
          <div className="mb-4 flex items-center gap-2">
            <Database size={18} />
            <h2 className="text-base font-semibold" style={{ color: 'var(--gr-text)' }}>
              策略基础信息
            </h2>
          </div>

          <form className="space-y-4" onSubmit={strategyForm.handleSubmit(onSaveStrategy)}>
            <div className="grid grid-cols-2 gap-3">
              <Field label="策略编码">
                <Input {...strategyForm.register('strategy_code')} />
              </Field>
              <Field label="策略类型">
                <Input {...strategyForm.register('strategy_type')} />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="作者 ID">
                <Input {...strategyForm.register('author_id')} />
              </Field>
              <Field label="运行状态">
                <Input {...strategyForm.register('run_status')} />
              </Field>
            </div>
            <Field label="策略名称">
              <Input {...strategyForm.register('name')} />
            </Field>
            <Field label="摘要">
              <Textarea rows={3} {...strategyForm.register('summary')} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="分类">
                <Input {...strategyForm.register('category_id')} />
              </Field>
              <Field label="资产类别">
                <Input {...strategyForm.register('asset_class')} />
              </Field>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <Field label="市场">
                <Input {...strategyForm.register('market')} />
              </Field>
              <Field label="风险">
                <select
                  className="h-9 rounded-md border border-input bg-transparent px-3 text-sm"
                  {...strategyForm.register('risk_level')}
                >
                  <option value="low">低</option>
                  <option value="medium">中</option>
                  <option value="high">高</option>
                </select>
              </Field>
              <Field label="发布状态">
                <Input {...strategyForm.register('pub_status')} />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="月订阅">
                <Input {...strategyForm.register('subscription_monthly')} />
              </Field>
              <Field label="年订阅">
                <Input {...strategyForm.register('subscription_yearly')} />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="回测开始">
                <Input type="date" {...strategyForm.register('backtest_start')} />
              </Field>
              <Field label="回测结束">
                <Input type="date" {...strategyForm.register('backtest_end')} />
              </Field>
            </div>
            <Button type="submit" disabled={strategyMutation.isPending} className="w-full">
              <Save />
              保存策略信息
            </Button>
            {strategyMutation.data && (
              <StatusLine ok text={`已保存：${strategyMutation.data.data.strategy_code}`} />
            )}
            {strategyMutation.error && <StatusLine text="保存失败，请检查字段和权限" />}
          </form>
        </section>

        <div className="space-y-5">
          <section className="rounded-lg bg-white p-5 card-shadow">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <FileUp size={18} />
                <h2 className="text-base font-semibold" style={{ color: 'var(--gr-text)' }}>
                  CSV 预检
                </h2>
              </div>
              <Button variant="outline" asChild>
                <a href={templateLinks[importType]} download>
                  <Download />
                  下载模板
                </a>
              </Button>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <Field label="导入类型">
                <select
                  className="h-9 rounded-md border border-input bg-transparent px-3 text-sm"
                  value={importType}
                  onChange={(event) => setImportType(event.target.value as ImportType)}
                >
                  <option value="strategy_daily_returns">日涨跌幅序列</option>
                  <option value="strategy_signals">历史信号</option>
                </select>
              </Field>
              <Field label="策略编码">
                <Input
                  value={strategyCodeForCsv}
                  onChange={(event) => setStrategyCodeForCsv(event.target.value)}
                />
              </Field>
              <Field label="写入模式">
                <select
                  className="h-9 rounded-md border border-input bg-transparent px-3 text-sm"
                  value={mode}
                  onChange={(event) => setMode(event.target.value as ImportMode)}
                >
                  <option value="upsert">新增或更新</option>
                  <option value="insert_only">仅新增</option>
                </select>
              </Field>
              <Field label="初始净值">
                <Input value={initialNav} onChange={(event) => setInitialNav(event.target.value)} />
              </Field>
            </div>

            {importType === 'strategy_daily_returns' && (
              <div className="mt-4">
                <Label className="mb-2">收益计算口径</Label>
                <Tabs
                  value={returnCalcMethod}
                  onValueChange={(value) => setReturnCalcMethod(value as ReturnCalcMethod)}
                >
                  <TabsList>
                    <TabsTrigger value="compound">复利</TabsTrigger>
                    <TabsTrigger value="simple">单利</TabsTrigger>
                  </TabsList>
                </Tabs>
              </div>
            )}

            <div className="mt-4 grid gap-3 md:grid-cols-[1fr_auto]">
              <Input
                type="file"
                accept=".csv,text/csv"
                onChange={(event) => setCsvFile(event.target.files?.[0] ?? null)}
              />
              <Button onClick={() => void onPreview()} disabled={!csvFile || previewMutation.isPending}>
                <Upload />
                预检
              </Button>
            </div>
          </section>

          {previewData && (
            <section className="rounded-lg bg-white p-5 card-shadow">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-base font-semibold" style={{ color: 'var(--gr-text)' }}>
                    预检结果
                  </h2>
                  <p className="mt-1 text-xs" style={{ color: 'var(--gr-text-secondary)' }}>
                    作业 {previewData.job_id}
                  </p>
                </div>
                <Button
                  onClick={() => previewData && commitMutation.mutate(previewData.job_id)}
                  disabled={!canCommit}
                >
                  <CheckCircle2 />
                  确认写入
                </Button>
              </div>

              <SummaryGrid summary={previewData.summary} status={previewData.status} />

              {previewData.errors.length > 0 && (
                <Alert variant="destructive" className="mt-4">
                  <AlertTitle>预检发现错误</AlertTitle>
                  <AlertDescription>
                    {previewData.errors.slice(0, 3).map((err) => (
                      <span key={`${err.row_number}-${err.column}-${err.error_code}`}>
                        第 {err.row_number} 行 {err.column ?? ''}：{err.message}
                      </span>
                    ))}
                  </AlertDescription>
                </Alert>
              )}

              {previewColumns.length > 0 && (
                <div className="mt-4">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        {previewColumns.map((column) => (
                          <TableHead key={column}>{column}</TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {previewData.preview_rows.slice(0, 8).map((row, index) => (
                        <TableRow key={index}>
                          {previewColumns.map((column) => (
                            <TableCell key={column}>{formatUnknown(row[column])}</TableCell>
                          ))}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </section>
          )}

          <section className="rounded-lg bg-white p-5 card-shadow">
            <h2 className="mb-4 text-base font-semibold" style={{ color: 'var(--gr-text)' }}>
              最近导入
            </h2>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>作业</TableHead>
                  <TableHead>类型</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>行数</TableHead>
                  <TableHead>时间</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(historyQuery.data?.data.list ?? []).map((job) => (
                  <TableRow key={job.job_id}>
                    <TableCell>{job.job_id}</TableCell>
                    <TableCell>{job.import_type}</TableCell>
                    <TableCell>{job.status}</TableCell>
                    <TableCell>{job.summary.valid_rows}</TableCell>
                    <TableCell>{job.created_at}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </section>
        </div>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block space-y-2">
      <Label>{label}</Label>
      {children}
    </label>
  )
}

function SummaryGrid({
  summary,
  status,
}: {
  summary: ImportPreviewData['summary']
  status: ImportPreviewData['status']
}) {
  const items = [
    ['状态', status],
    ['总行数', summary.total_rows],
    ['有效行', summary.valid_rows],
    ['错误行', summary.error_rows],
    ['将新增', summary.will_insert],
    ['将更新', summary.will_update],
    ['计算口径', summary.return_calc_method ?? '-'],
    ['派生月度', summary.derived_monthly_rows ?? 0],
  ]
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {items.map(([label, value]) => (
        <div key={label} className="rounded-md border border-border bg-muted/30 p-3">
          <div className="text-xs" style={{ color: 'var(--gr-text-secondary)' }}>
            {label}
          </div>
          <div className="mt-1 text-sm font-semibold tabular" style={{ color: 'var(--gr-text)' }}>
            {value}
          </div>
        </div>
      ))}
    </div>
  )
}

function StatusLine({ ok = false, text }: { ok?: boolean; text: string }) {
  return (
    <div
      className="rounded-md px-3 py-2 text-sm"
      style={{
        background: ok ? 'var(--gr-green-light)' : 'var(--gr-red-light)',
        color: ok ? 'var(--gr-green)' : 'var(--gr-red)',
      }}
    >
      {text}
    </div>
  )
}

function optionalText(value: string | undefined) {
  const trimmed = value?.trim()
  return trimmed ? trimmed : null
}

function formatUnknown(value: unknown) {
  if (value === null || value === undefined) {
    return ''
  }
  if (typeof value === 'object') {
    return JSON.stringify(value)
  }
  return String(value)
}
