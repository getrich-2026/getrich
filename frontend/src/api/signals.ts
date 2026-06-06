import { apiFetch, type ApiResponse } from "./client";

// ---------------------------------------------------------------------------
// Types — match backend signal response shapes
// ---------------------------------------------------------------------------

export type SignalType = "entry" | "exit" | "adjust" | "alert";
export type SignalAction = "buy" | "sell" | "hold" | "close";
export type SignalDirection = "long" | "short";
export type SignalUrgency = "critical" | "high" | "normal" | "low";
export type SignalStatus = "active" | "expired" | "cancelled";

/** Compact strategy reference embedded in signal responses. */
export interface SignalStrategyRef {
  id: string;
  name: string;
  category?: string;
  risk_level?: string;
}

/** Reason detail sub-object (strategy-dependent). */
export interface ReasonDetail {
  spread_current: number;
  spread_mean: number;
  z_score: number;
  trigger_rule: string;
}

/** Market snapshot at signal generation time. */
export interface MarketSnapshot {
  symbol: string;
  snapshot_time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  open_interest: number;
  indicators: {
    ma5: number;
    ma20: number;
    rsi_14: number;
    atr_14: number;
  };
}

/** Historical performance of similar past signals. */
export interface HistoricalPerformance {
  similar_signals_count: number;
  win_rate: number;
  avg_return: number;
  avg_holding_days: number;
}

/** Per-user state for this signal (null if not authenticated). */
export interface UserSignalState {
  is_read: boolean;
  read_at: string | null;
  is_executed: boolean;
  executed_price: number | null;
  note: string | null;
}

/** Full signal detail (GET /signals/{code}). */
export interface SignalDetail {
  id: string;
  strategy: SignalStrategyRef;
  signal_type: SignalType;
  action: SignalAction;
  direction: SignalDirection;
  symbol: string;
  symbol_name: string;
  exchange: string;
  trigger_price: number;
  target_price: number;
  stop_loss_price: number;
  suggested_quantity: number;
  position_pct: number;
  confidence: number;
  urgency: SignalUrgency;
  reason: string;
  reason_detail: ReasonDetail | null;
  trigger_time: string;
  status: SignalStatus;
  expired_at: string | null;
  market_snapshot: MarketSnapshot | null;
  historical_performance: HistoricalPerformance | null;
  user_state: UserSignalState | null;
}

/** Request body for POST /signals/{code}/execute. */
export interface ExecuteSignalRequest {
  executed_price?: number;
  executed_quantity?: number;
  executed_at?: string; // ISO datetime
  note?: string;
}

/** Response from POST /signals/{code}/execute. */
export interface ExecuteSignalResult {
  signal_id: string;
  is_executed: boolean;
  executed_price: number;
  executed_at: string;
  slippage: number;
  slippage_pct: number;
}

/** Response from POST /signals/{code}/read. */
export interface MarkReadResult {
  signal_id: string;
  is_read: boolean;
  read_at: string;
  remaining_unread: number;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/** Fetch full signal detail. */
export function getSignalDetail(
  signalCode: string,
): Promise<ApiResponse<SignalDetail>> {
  return apiFetch<ApiResponse<SignalDetail>>(
    `/signals/${encodeURIComponent(signalCode)}`,
  );
}

/** Mark a signal as read. Idempotent (UPSERT). */
export function markSignalRead(
  signalCode: string,
): Promise<ApiResponse<MarkReadResult>> {
  return apiFetch<ApiResponse<MarkReadResult>>(
    `/signals/${encodeURIComponent(signalCode)}/read`,
    { method: "POST" },
  );
}

/** Record execution for a signal. Also marks it as read. */
export function executeSignal(
  signalCode: string,
  body: ExecuteSignalRequest,
): Promise<ApiResponse<ExecuteSignalResult>> {
  return apiFetch<ApiResponse<ExecuteSignalResult>>(
    `/signals/${encodeURIComponent(signalCode)}/execute`,
    { method: "POST", body: JSON.stringify(body) },
  );
}
