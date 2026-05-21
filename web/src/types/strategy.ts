import type { Pagination } from './common'

// ==== 策略列表 ====
export interface StrategyListParams {
  category_id?: string
  asset_class?: string
  risk_level?: string
  sort?: string
  sort_order?: string
  keyword?: string
  status?: string
  page?: number
  page_size?: number
}

export interface Strategy {
  id: string
  name: string
  asset_class: string
  market: string
  risk_level: string
  subscriber_count: number
  is_subscribed: boolean
  subscription_price: {
    monthly: number
    yearly: number
  }
  performance: {
    annualized_return: number
    max_drawdown: number
    sharpe_ratio: number
    win_rate: number
  }
}

export interface StrategyListData {
  list: Strategy[]
  pagination: Pagination
  order: {
    field: string
    direction: string
  }
}

// ==== 策略分类 ====
export interface StrategyCategory {
  id: string
  name: string
  description: string
  icon_url: string
  strategy_count: number
}

export interface GetCategoriesResponse {
  categories: StrategyCategory[]
}

// ==== 策略详情 ====
export interface StrategyCreator {
  id: string
  name: string
  avatar: string
  bio: string
}

export interface StrategyPerformance {
  total_return: number
  annualized_return: number
  max_drawdown: number
  sharpe_ratio: number
  sortino_ratio: number
  win_rate: number
  total_trades: number
}

export interface StrategySubscriptionInfo {
  subscription_id: string
  plan_type: 'monthly' | 'yearly'
  start_date: string
  expire_date: string
  auto_renew: boolean
}

export interface StrategyDetail {
  id: string
  name: string
  description: string
  detail_html: string
  category: {
    id: string
    name: string
  }
  asset_class: string
  market: string
  risk_level: 'low' | 'medium' | 'high'
  status: 'active' | 'inactive'
  tags: string[]
  creator: StrategyCreator
  performance: StrategyPerformance
  backtest_period: {
    start: string
    end: string
  }
  subscriber_count: number
  is_subscribed: boolean
  subscription_info: StrategySubscriptionInfo | null
  subscription_price: {
    monthly: number
    yearly: number
  }
  published_at: string
  updated_at: string
}

// ==== 净值曲线 ====
export interface EquityCurveParams {
  period?: '1m' | '3m' | '6m' | '1y' | '3y' | 'all'
  start_date?: string
  end_date?: string
  include_benchmark?: boolean
  include_drawdown?: boolean
}

export interface EquityCurvePoint {
  date: string
  nav: number
  cumulative_return: number
  daily_return: number
  position_ratio: number
}

export interface BenchmarkPoint {
  date: string
  nav: number
}

export interface DrawdownPoint {
  date: string
  drawdown: number
}

export interface EquityCurveData {
  strategy_id: string
  period: {
    start: string
    end: string
  }
  equity_curve: EquityCurvePoint[]
  benchmark_curve: BenchmarkPoint[]
  drawdown_curve: DrawdownPoint[]
  total_points: number
}

// ==== 月度收益矩阵 ====
export interface MonthlyReturnRow {
    year: number
    /** tips：months 用 (number | null)[] 而不是 number[]，因为 2026 年未来月份后端返回的是 null，渲染表格时记得判断一下再格式化成百分比，否则会报错。 */
    months: (number | null)[]
    yearly_return: number
}

export interface MonthlyReturnsData {
    strategy_id: string
    matrix: MonthlyReturnRow[]
}

// ==== 回测报告 ====
export interface BacktestSummary {
  backtest_start: string
  backtest_end: string
  initial_capital: number
  final_capital: number
  total_return: number
  annualized_return: number
  max_drawdown: number
  /** tips: 这3个 max_drawdown_* 字段是回撤的开始、结束、修复日期，后面画净值曲线图时可以用来标注回撤区间，记一下。 */
  max_drawdown_start: string
  max_drawdown_end: string
  max_drawdown_recovery: string
  sharpe_ratio: number
}

export interface BacktestRiskAnalysis {
  var_95: number
  cvar_95: number
  beta: number
  alpha: number
  max_single_day_loss: number
  max_single_day_gain: number
}

export interface BacktestTradeAnalysis {
  total_trades: number
  win_rate: number
  avg_trade_return: number
  avg_holding_days: number
  profit_factor: number
}

export interface BacktestAnnualRow {
  year: number
  return: number
  max_drawdown: number
  sharpe: number
  trades: number
}

export interface BacktestReportData {
  strategy_id: string
  summary: BacktestSummary
  risk_analysis: BacktestRiskAnalysis
  trade_analysis: BacktestTradeAnalysis
  annual_performance: BacktestAnnualRow[]
}

// ==== 历史交易记录 ====
export interface TradeListParams {
  start_date?: string
  end_date?: string
  action?: 'all' | 'buy' | 'sell'
  result?: 'all' | 'win' | 'loss'
  page?: number
  page_size?: number
}

export interface TradeRecord {
  trade_id: string
  entry_signal_id: string
  exit_signal_id: string
  symbol: string
  /** tips: 文档未给出枚举值，根据 response 示例推断为 'long' | 'short'，联调时确认。*/
  direction: 'long' | 'short'
  entry_price: number
  entry_time: string
  exit_price: number
  exit_time: string
  quantity: number
  pnl: number
  return_pct: number
  holding_days: number
}

export interface TradeListData {
  list: TradeRecord[]
  pagination: Pagination
}

// ==== 历史信号列表 ====
export interface SignalListParams {
  type?: 'entry' | 'exit' | 'adjust' | 'alert' | 'all'
  action?: 'buy' | 'sell' | 'hold' | 'close' | 'all'
  status?: 'active' | 'expired' | 'cancelled' | 'all'
  page?: number
  page_size?: number
}

export interface SignalRecord {
  id: string
  signal_type: 'entry' | 'exit' | 'adjust' | 'alert'
  action: 'buy' | 'sell' | 'hold' | 'close'
  symbol: string
  trigger_price: number
  confidence: number
  /** tips: urgency 字段 response 里只出现了 high，我补全了 medium 和 low，符合常规逻辑，如果后端文档有明确枚举值以文档为准。 */
  urgency: 'high' | 'medium' | 'low'
  trigger_time: string
  is_read: boolean
  is_executed: boolean
  status: 'active' | 'expired' | 'cancelled'
}

export interface SignalListData {
  list: SignalRecord[]
  pagination: Pagination
}