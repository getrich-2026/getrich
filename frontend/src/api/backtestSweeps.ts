import { apiFetch, type ApiResponse } from "./client";
import type { PaginationInfo } from "./backtests";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type BacktestSweepStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";
export type BacktestSweepTrialStatus = "completed" | "failed";

export interface BacktestSweepSummary {
  sweep_id: string;
  search_type: string;
  search_spec: Record<string, unknown>;
  select_metric: string;
  maximize: boolean;
  status: BacktestSweepStatus;
  total_trials: number;
  completed_trials: number;
  failed_trials: number;
  best_trial_id: string | null;
  best_run_id: string | null;
  best_metric_value: number | null;
  created_at: string;
  completed_at: string | null;
  updated_at: string;
}

export interface BacktestSweepDetail extends BacktestSweepSummary {
  summary_json: Record<string, unknown>;
  /**
   * Job linkage to the parent `backtest_jobs` row (matched on
   * `ref_id == sweep_id`). All three fields are `null` between job
   * create and runner claim (typically <1s). The frontend uses
   * `job_id` to open the existing `/backtest-jobs/{job_id}/events`
   * SSE channel for live progress, and `job_status` / `progress` as
   * the authoritative source for the progress bar before the sweep
   * row itself is updated.
   */
  job_id: string | null;
  progress: number | null;
  job_status: BacktestSweepStatus | null;
}

export interface BacktestSweepTrial {
  trial_id: string;
  sweep_id: string;
  run_id: string;
  trial_index: number;
  params: Record<string, unknown>;
  param_fingerprint: string;
  status: BacktestSweepTrialStatus;
  error_message: string | null;
  select_metric_value: number | null;
  metrics_json: Record<string, unknown>;
  created_at: string;
  completed_at: string | null;
  updated_at: string;
}

export interface BacktestSweepListResponse {
  list: BacktestSweepSummary[];
  pagination: PaginationInfo;
}

export interface BacktestSweepTrialListResponse {
  list: BacktestSweepTrial[];
  pagination: PaginationInfo;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export function listBacktestSweeps(params?: {
  status?: BacktestSweepStatus;
  page?: number;
  page_size?: number;
}): Promise<BacktestSweepListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.status) searchParams.set("status", params.status);
  if (params?.page !== undefined) searchParams.set("page", String(params.page + 1));
  if (params?.page_size !== undefined) {
    searchParams.set("page_size", String(params.page_size));
  }
  const qs = searchParams.toString();
  return apiFetch<ApiResponse<BacktestSweepListResponse>>(
    `/backtest-sweeps${qs ? `?${qs}` : ""}`,
  ).then((res) => res.data);
}

export function getBacktestSweep(sweepId: string): Promise<BacktestSweepDetail> {
  return apiFetch<ApiResponse<BacktestSweepDetail>>(
    `/backtest-sweeps/${encodeURIComponent(sweepId)}`,
  ).then((res) => res.data);
}

export function listBacktestSweepTrials(
  sweepId: string,
  params?: {
    status?: BacktestSweepTrialStatus;
    page?: number;
    page_size?: number;
  },
): Promise<BacktestSweepTrialListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.status) searchParams.set("status", params.status);
  if (params?.page !== undefined) searchParams.set("page", String(params.page + 1));
  if (params?.page_size !== undefined) {
    searchParams.set("page_size", String(params.page_size));
  }
  const qs = searchParams.toString();
  return apiFetch<ApiResponse<BacktestSweepTrialListResponse>>(
    `/backtest-sweeps/${encodeURIComponent(sweepId)}/trials${qs ? `?${qs}` : ""}`,
  ).then((res) => res.data);
}
