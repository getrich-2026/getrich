import { apiFetch, type PaginatedResponse, type ApiResponse } from "./client";

// ---------------------------------------------------------------------------
// Data types
// ---------------------------------------------------------------------------

export interface StrategySummary {
  id: string;
  name: string;
  code?: string;
  status?: string;
  symbols?: string[];
  created_at?: string;
  updated_at?: string;
  description?: string;
  asset_class?: string;
  market?: string;
  risk_level?: string;
  subscriber_count: number;
  is_subscribed: boolean;
  subscription_price: {
    monthly: number;
    yearly: number;
  };
  performance?: {
    annualized_return: number;
    max_drawdown: number;
    sharpe_ratio: number;
    win_rate: number;
  };
}

export interface SignalRecord {
  id: string; // signal_code
  signal_type: string;
  action: string;
  symbol: string;
  trigger_price: number;
  confidence: number;
  urgency: string;
  trigger_time: string;
  is_read: boolean;
  is_executed: boolean;
  status: string;
}

export interface TradeRecord {
  id: string;
  strategy_id: string;
  signal_id: string | null;
  symbol: string;
  action: string;
  quantity: number;
  price: number;
  notional: number;
  fee: number;
  avg_cost: number | null;
  realized_pnl: number;
  cumulative_pnl: number | null;
  executed_at: string;
  bar_dt: string | null;
  tag: string | null;
}

// ---------------------------------------------------------------------------
// Equity curve types
// ---------------------------------------------------------------------------

export interface EquityPoint {
  date: string;
  nav: number;
  cumulative_return: number;
  daily_return: number;
  position_ratio: number;
}

export interface BenchmarkPoint {
  date: string;
  nav: number;
}

export interface DrawdownPoint {
  date: string;
  drawdown: number;
}

export interface EquityCurveData {
  strategy_id: string;
  period: { start: string; end: string };
  equity_curve: EquityPoint[];
  benchmark_curve: BenchmarkPoint[];
  drawdown_curve: DrawdownPoint[];
  total_points: number;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/** List all strategies. Backend wraps in ApiResponse<{list, pagination, order}>. */
export function listStrategies(): Promise<StrategySummary[]> {
  return apiFetch<ApiResponse<{ list: StrategySummary[] }>>("/strategies").then(
    (res) => res.data.list,
  );
}

/** List signals for a strategy with optional filters. */
export function listSignals(
  strategyCode: string,
  params?: {
    limit?: number;
    offset?: number;
    start_date?: string;
    end_date?: string;
    action?: string;
    result?: string;
  },
): Promise<PaginatedResponse<SignalRecord>> {
  const searchParams = new URLSearchParams();
  if (params?.limit !== undefined)
    searchParams.set("limit", String(params.limit));
  if (params?.offset !== undefined)
    searchParams.set("offset", String(params.offset));
  if (params?.start_date) searchParams.set("start_date", params.start_date);
  if (params?.end_date) searchParams.set("end_date", params.end_date);
  if (params?.action) searchParams.set("action", params.action);
  if (params?.result) searchParams.set("result", params.result);

  const qs = searchParams.toString();
  return apiFetch<PaginatedResponse<SignalRecord>>(
    `/strategies/${encodeURIComponent(strategyCode)}/signals${qs ? `?${qs}` : ""}`,
  );
}

/** List trades for a strategy with optional filters. */
export function listTrades(
  strategyCode: string,
  params?: {
    limit?: number;
    offset?: number;
    start_date?: string;
    end_date?: string;
    action?: string;
    result?: string;
  },
): Promise<PaginatedResponse<TradeRecord>> {
  const searchParams = new URLSearchParams();
  if (params?.limit !== undefined)
    searchParams.set("limit", String(params.limit));
  if (params?.offset !== undefined)
    searchParams.set("offset", String(params.offset));
  if (params?.start_date) searchParams.set("start_date", params.start_date);
  if (params?.end_date) searchParams.set("end_date", params.end_date);
  if (params?.action) searchParams.set("action", params.action);
  if (params?.result) searchParams.set("result", params.result);

  const qs = searchParams.toString();
  return apiFetch<PaginatedResponse<TradeRecord>>(
    `/strategies/${encodeURIComponent(strategyCode)}/trades${qs ? `?${qs}` : ""}`,
  );
}

/** Get full strategy detail (for edit form pre-population). */
export function getStrategyDetail(
  strategyCode: string,
): Promise<ApiResponse<StrategyDetail>> {
  return apiFetch<ApiResponse<StrategyDetail>>(
    `/strategies/${encodeURIComponent(strategyCode)}`,
  );
}

/** Update strategy metadata. Only sends non-null fields. */
export function updateStrategy(
  strategyCode: string,
  body: Partial<StrategyUpdateFields>,
): Promise<ApiResponse<StrategyDetail>> {
  return apiFetch<ApiResponse<StrategyDetail>>(
    `/strategies/${encodeURIComponent(strategyCode)}`,
    { method: "PUT", body: JSON.stringify(body) },
  );
}

// ---------------------------------------------------------------------------
// Detail types
// ---------------------------------------------------------------------------

export interface StrategyDetail {
  id: string;
  name: string;
  description: string;
  detail_html: string;
  category: { id: string; name: string };
  asset_class: string;
  market: string;
  risk_level: string;
  status: string;
  tags: string[];
  creator: { id: string; name: string; avatar: string; bio: string };
  performance: Record<string, number>;
  backtest_period: { start: string; end: string };
  subscriber_count: number;
  is_subscribed: boolean;
  subscription_info: null | Record<string, unknown>;
  subscription_price: { monthly: number; yearly: number };
  published_at: string;
  updated_at: string;
}

export interface StrategyUpdateFields {
  name?: string;
  description?: string;
  detail_html?: string;
  category_id?: string;
  asset_class?: string;
  market?: string;
  risk_level?: string;
  run_status?: string;
  subscription_monthly?: number;
  subscription_yearly?: number;
  backtest_start?: string;
  backtest_end?: string;
}

/** Fetch equity curve data for a strategy. */
export function getEquityCurve(
  strategyCode: string,
  params?: {
    period?: string;
    start_date?: string;
    end_date?: string;
    include_benchmark?: boolean;
    include_drawdown?: boolean;
  },
): Promise<ApiResponse<EquityCurveData>> {
  const searchParams = new URLSearchParams();
  if (params?.period) searchParams.set("period", params.period);
  if (params?.start_date) searchParams.set("start_date", params.start_date);
  if (params?.end_date) searchParams.set("end_date", params.end_date);
  if (params?.include_benchmark !== undefined)
    searchParams.set("include_benchmark", String(params.include_benchmark));
  if (params?.include_drawdown !== undefined)
    searchParams.set("include_drawdown", String(params.include_drawdown));
  const qs = searchParams.toString();
  return apiFetch<ApiResponse<EquityCurveData>>(
    `/strategies/${encodeURIComponent(strategyCode)}/equity-curve${qs ? `?${qs}` : ""}`,
  );
}
