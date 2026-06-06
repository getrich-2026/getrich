import { apiFetch, type ApiResponse } from "./client";
import type { PaginationInfo } from "./backtests";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type BacktestWalkForwardStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";
export type BacktestWalkForwardWindowStatus = "completed" | "failed";

export interface BacktestWalkForwardSummary {
  walk_forward_id: string;
  search_type: string;
  search_spec: Record<string, unknown>;
  select_metric: string;
  maximize: boolean;
  refit: string;
  status: BacktestWalkForwardStatus;
  total_windows: number;
  completed_windows: number;
  failed_windows: number;
  mean_validation_metric: number | null;
  created_at: string;
  completed_at: string | null;
  updated_at: string;
}

export interface BacktestWalkForwardDetail extends BacktestWalkForwardSummary {
  summary_json: Record<string, unknown>;
  /**
   * Job linkage to the parent `backtest_jobs` row (matched on
   * `ref_id == walk_forward_id`). All three fields are `null` between
   * job create and runner claim. See `BacktestSweepDetail` for the
   * field semantics; the SSE channel is identical.
   */
  job_id: string | null;
  progress: number | null;
  job_status: BacktestWalkForwardStatus | null;
}

export interface BacktestWalkForwardWindow {
  walk_forward_id: string;
  window_index: number;
  train_start: string;
  train_end: string;
  val_start: string;
  val_end: string;
  status: BacktestWalkForwardWindowStatus;
  error_message: string | null;
  train_sweep_id: string | null;
  best_trial_id: string | null;
  best_run_id: string | null;
  validation_run_id: string | null;
  best_params: Record<string, unknown>;
  train_metric_value: number | null;
  validation_metric_value: number | null;
  validation_metrics_json: Record<string, unknown>;
  created_at: string;
  completed_at: string | null;
  updated_at: string;
}

export interface BacktestWalkForwardEquityPoint {
  walk_forward_id: string;
  window_index: number;
  run_id: string;
  strategy_name: string;
  dt: string;
  cash: number | null;
  equity: number;
  trading_pnl: number | null;
  mtm_pnl: number | null;
  total_fees: number | null;
  gross_exposure: number | null;
  row_json: Record<string, unknown>;
  created_at: string;
}

export interface BacktestWalkForwardListResponse {
  list: BacktestWalkForwardSummary[];
  pagination: PaginationInfo;
}

export interface BacktestWalkForwardWindowListResponse {
  list: BacktestWalkForwardWindow[];
  pagination: PaginationInfo;
}

export interface BacktestWalkForwardEquityCurveResponse {
  points: BacktestWalkForwardEquityPoint[];
  total_points: number;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export function listBacktestWalkForwards(params?: {
  status?: BacktestWalkForwardStatus;
  page?: number;
  page_size?: number;
}): Promise<BacktestWalkForwardListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.status) searchParams.set("status", params.status);
  if (params?.page !== undefined) searchParams.set("page", String(params.page + 1));
  if (params?.page_size !== undefined) {
    searchParams.set("page_size", String(params.page_size));
  }
  const qs = searchParams.toString();
  return apiFetch<ApiResponse<BacktestWalkForwardListResponse>>(
    `/backtest-walk-forwards${qs ? `?${qs}` : ""}`,
  ).then((res) => res.data);
}

export function getBacktestWalkForward(
  walkForwardId: string,
): Promise<BacktestWalkForwardDetail> {
  return apiFetch<ApiResponse<BacktestWalkForwardDetail>>(
    `/backtest-walk-forwards/${encodeURIComponent(walkForwardId)}`,
  ).then((res) => res.data);
}

export function listBacktestWalkForwardWindows(
  walkForwardId: string,
  params?: {
    status?: BacktestWalkForwardWindowStatus;
    page?: number;
    page_size?: number;
  },
): Promise<BacktestWalkForwardWindowListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.status) searchParams.set("status", params.status);
  if (params?.page !== undefined) searchParams.set("page", String(params.page + 1));
  if (params?.page_size !== undefined) {
    searchParams.set("page_size", String(params.page_size));
  }
  const qs = searchParams.toString();
  return apiFetch<ApiResponse<BacktestWalkForwardWindowListResponse>>(
    `/backtest-walk-forwards/${encodeURIComponent(walkForwardId)}/windows${qs ? `?${qs}` : ""}`,
  ).then((res) => res.data);
}

export function getBacktestWalkForwardOosEquityCurve(
  walkForwardId: string,
): Promise<BacktestWalkForwardEquityCurveResponse> {
  return apiFetch<ApiResponse<BacktestWalkForwardEquityCurveResponse>>(
    `/backtest-walk-forwards/${encodeURIComponent(walkForwardId)}/oos-equity-curve`,
  ).then((res) => res.data);
}
