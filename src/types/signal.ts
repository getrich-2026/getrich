import type { Pagination } from './common'

// ===== 信号流 =====
export interface SignalFeedParams {
  strategy_id?: string
  strategy_ids?: string[]   // axios 默认序列化为 strategy_ids[]=v1&strategy_ids[]=v2
                            // 如果后端要求逗号分隔，联调时在 client.ts 配置 paramsSerializer
  signal_type?: 'entry' | 'exit' | 'adjust' | 'alert'
  action?: 'buy' | 'sell' | 'hold' | 'close'
  asset_class?: string
  is_read?: boolean
  confidence_min?: number
  start_date?: string
  end_date?: string
  page?: number
  page_size?: number
}

export interface SignalStrategyRef {
  id: string
  name: string
}

export interface SignalItem {
  id: string
  strategy: SignalStrategyRef
  signal_type: 'entry' | 'exit' | 'adjust' | 'alert'
  action: 'buy' | 'sell' | 'hold' | 'close'
  direction: 'long' | 'short'
  symbol: string
  symbol_name: string
  exchange: string
  trigger_price: number
  target_price: number
  stop_loss_price: number
  confidence: number
  urgency: 'high' | 'medium' | 'low'
  reason: string
  trigger_time: string
  is_read: boolean
  is_executed: boolean
  status: 'active' | 'expired' | 'cancelled'
}

export interface SignalFeedData {
  list: SignalItem[]
  pagination: Pagination
  unread_count: number  // 列表顶部的未读 badge 用这个，不用单独再请求一次
}

// ===== 未读统计 =====
export interface UnreadByStrategy {
  strategy_id: string
  strategy_name: string
  unread_count: number
  latest_signal_time: string
}

export interface UnreadByUrgency {
  critical: number
  high: number
  normal: number
  low: number
}

export interface UnreadSummaryData {
  total_unread: number
  by_strategy: UnreadByStrategy[]
  by_urgency: UnreadByUrgency
}

// ===== 信号详情 =====

// 详情里的 strategy 比列表多了 category / risk_level
export interface SignalStrategyDetail {
  id: string
  name: string
  category: string
  risk_level: 'low' | 'medium' | 'high'
}

export interface SignalReasonDetail {
  spread_current: number
  spread_mean: number
  z_score: number
  trigger_rule: string
}

export interface MarketIndicators {
  ma5: number
  ma20: number
  rsi_14: number
  atr_14: number
}

export interface MarketSnapshot {
  symbol: string
  snapshot_time: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  open_interest: number
  indicators: MarketIndicators
}

export interface HistoricalPerformance {
  similar_signals_count: number
  win_rate: number
  avg_return: number
  avg_holding_days: number
}

export interface SignalUserState {
  is_read: boolean
  read_at: string | null
  is_executed: boolean
  executed_price: number | null
  note: string | null
}

export interface SignalDetail {
  id: string
  strategy: SignalStrategyDetail
  signal_type: 'entry' | 'exit' | 'adjust' | 'alert'
  action: 'buy' | 'sell' | 'hold' | 'close'
  direction: 'long' | 'short'
  symbol: string
  symbol_name: string
  exchange: string
  trigger_price: number
  target_price: number
  stop_loss_price: number
  suggested_quantity: number
  position_pct: number
  confidence: number
  urgency: 'critical' | 'high' | 'medium' | 'low'
  reason: string
  reason_detail: SignalReasonDetail
  trigger_time: string
  status: 'active' | 'expired' | 'cancelled'
  expired_at: string | null
  market_snapshot: MarketSnapshot
  historical_performance: HistoricalPerformance
  user_state: SignalUserState
}

// ===== 标记已读 =====
export interface MarkReadData {
  signal_id: string
  is_read: boolean
  read_at: string
  remaining_unread: number
}

// ===== 记录执行反馈 =====
export interface ExecuteSignalBody {
  executed_price?: number
  executed_quantity?: number
  executed_at?: string   // 不传后端取当前时间
  note?: string
}

export interface ExecuteSignalData {
  signal_id: string
  is_executed: boolean
  executed_price: number
  executed_at: string
  slippage: number       // 绝对滑点
  slippage_pct: number   // 滑点百分比
}