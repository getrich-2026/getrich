import { apiFetch, type ApiResponse } from "./client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type BacktestJobType = "backtest" | "sweep" | "walk_forward";

export type BacktestJobStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type BacktestBarLoader = "pg" | "duckdb";

export interface PaginationInfo {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  has_more?: boolean;
}

export interface BacktestJobSummary {
  job_id: string;
  job_type: BacktestJobType;
  ref_id: string;
  status: BacktestJobStatus;
  progress: number;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string;
}

export interface BacktestJobDetail extends BacktestJobSummary {
  request_json: Record<string, unknown>;
}

export interface BacktestJobListResponse {
  list: BacktestJobSummary[];
  pagination: PaginationInfo;
}

export interface BacktestRunRequest {
  strategy_name: string;
  symbols: string[];
  start: string;
  end: string;
  initial_cash: string;
  freq: string;
  bar_loader: BacktestBarLoader;
  max_attempts: number;
  extra_freqs: string[];
  execution_lag_bars: number;
  strategy_params: Record<string, unknown>;
  save_artifacts: boolean;
}

export interface BacktestSearchSpec {
  space: Record<string, unknown>;
  constraints?: unknown[];
}

export interface SweepRunRequest {
  strategy_name: string;
  symbols: string[];
  start: string;
  end: string;
  initial_cash: string;
  freq: string;
  bar_loader: BacktestBarLoader;
  max_attempts: number;
  sweep_id?: string;
  search_type: "grid";
  search_spec: BacktestSearchSpec;
  select_metric: string;
  maximize: boolean;
  fail_fast: boolean;
  strategy_params: Record<string, unknown>;
}

export interface WalkForwardRunRequest {
  strategy_name: string;
  symbols: string[];
  start: string;
  end: string;
  initial_cash: string;
  freq: string;
  bar_loader: BacktestBarLoader;
  max_attempts: number;
  walk_forward_id?: string;
  search_spec: BacktestSearchSpec;
  train_months: number;
  val_months: number;
  step_months?: number;
  refit: "rolling" | "anchored";
  select_metric: string;
  maximize: boolean;
  fail_fast: boolean;
  strategy_params: Record<string, unknown>;
}

export interface BacktestJobCreateResponse {
  job_id: string;
  ref_id: string;
  status: BacktestJobStatus;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export function listBacktestJobs(params?: {
  job_type?: BacktestJobType;
  status?: BacktestJobStatus;
  page?: number;
  page_size?: number;
}): Promise<BacktestJobListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.job_type) searchParams.set("job_type", params.job_type);
  if (params?.status) searchParams.set("status", params.status);
  if (params?.page !== undefined) searchParams.set("page", String(params.page + 1));
  if (params?.page_size !== undefined) {
    searchParams.set("page_size", String(params.page_size));
  }
  const qs = searchParams.toString();
  return apiFetch<ApiResponse<BacktestJobListResponse>>(
    `/backtest-jobs${qs ? `?${qs}` : ""}`,
  ).then((res) => res.data);
}

export function getBacktestJob(jobId: string): Promise<BacktestJobDetail> {
  return apiFetch<ApiResponse<BacktestJobDetail>>(
    `/backtest-jobs/${encodeURIComponent(jobId)}`,
  ).then((res) => res.data);
}

function idempotencyHeaders(idempotencyKey?: string): Record<string, string> {
  const headers: Record<string, string> = {};
  if (idempotencyKey) {
    headers["Idempotency-Key"] = idempotencyKey;
  }
  return headers;
}

export function createBacktestJob(
  body: BacktestRunRequest,
  idempotencyKey?: string,
): Promise<BacktestJobCreateResponse> {
  return apiFetch<ApiResponse<BacktestJobCreateResponse>>("/backtest-jobs/backtest", {
    method: "POST",
    headers: idempotencyHeaders(idempotencyKey),
    body: JSON.stringify(body),
  }).then((res) => res.data);
}

export function createSweepJob(
  body: SweepRunRequest,
  idempotencyKey?: string,
): Promise<BacktestJobCreateResponse> {
  return apiFetch<ApiResponse<BacktestJobCreateResponse>>("/backtest-jobs/sweep", {
    method: "POST",
    headers: idempotencyHeaders(idempotencyKey),
    body: JSON.stringify(body),
  }).then((res) => res.data);
}

export function createWalkForwardJob(
  body: WalkForwardRunRequest,
  idempotencyKey?: string,
): Promise<BacktestJobCreateResponse> {
  return apiFetch<ApiResponse<BacktestJobCreateResponse>>("/backtest-jobs/walk-forward", {
    method: "POST",
    headers: idempotencyHeaders(idempotencyKey),
    body: JSON.stringify(body),
  }).then((res) => res.data);
}

export function cancelBacktestJob(jobId: string): Promise<BacktestJobDetail> {
  return apiFetch<ApiResponse<BacktestJobDetail>>(
    `/backtest-jobs/${encodeURIComponent(jobId)}/cancel`,
    { method: "POST" },
  ).then((res) => res.data);
}
