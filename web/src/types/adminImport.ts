export type ImportType = 'strategy_daily_returns' | 'strategy_signals'
export type ImportMode = 'upsert' | 'insert_only'
export type ReturnCalcMethod = 'compound' | 'simple'

export interface StrategyUpsertBody {
  strategy_code: string
  name: string
  strategy_type: string
  summary?: string | null
  description?: string | null
  detail_html?: string | null
  category_id?: string | null
  asset_class: string
  market: string
  risk_level: 'low' | 'medium' | 'high'
  run_status: string
  pub_status: string
  author_id: string
  cover_image?: string | null
  subscription_monthly: string
  subscription_yearly: string
  backtest_start?: string | null
  backtest_end?: string | null
}

export interface StrategyUpsertData {
  strategy_id: string
  strategy_code: string
  name: string
  pub_status: string
  run_status: string
}

export interface ImportPreviewBody {
  import_type: ImportType
  csv_text: string
  file_name: string
  strategy_code?: string | null
  mode: ImportMode
  return_calc_method: ReturnCalcMethod
  initial_nav: number
  trading_days_per_year: number
  risk_free_rate: number
}

export interface ImportSummary {
  total_rows: number
  valid_rows: number
  error_rows: number
  duplicate_rows: number
  will_insert: number
  will_update: number
  return_calc_method?: ReturnCalcMethod
  initial_nav?: number
  trading_days_per_year?: number
  risk_free_rate?: number
  derived_equity_rows?: number
  derived_monthly_rows?: number
  derived_snapshot_rows?: number
  affected_rows?: number
}

export interface ImportErrorRow {
  row_number: number
  column: string | null
  error_code: string
  message: string
  raw_row: Record<string, unknown>
}

export interface ImportPreviewData {
  job_id: string
  status: 'validated' | 'blocked'
  summary: ImportSummary
  preview_rows: Record<string, unknown>[]
  errors: ImportErrorRow[]
}

export interface ImportCommitData {
  job_id: string
  status: 'committed'
  affected_rows: number
}

export interface ImportJob {
  job_id: string
  import_type: ImportType
  file_name: string
  mode: ImportMode
  status: 'validated' | 'blocked' | 'committed'
  summary: ImportSummary
  created_by: string
  committed_by: string | null
  created_at: string
  committed_at: string
}

export interface ImportHistoryData {
  list: ImportJob[]
}
