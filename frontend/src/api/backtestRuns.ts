import { _fetchWithAuth, apiFetch, ApiClientError, type ApiResponse } from "./client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type BacktestRunStatus = "running" | "completed" | "failed";

export interface BacktestRunSummary {
  run_id: string;
  strategy_id: string;
  strategy_name: string;
  strategy_names: string[];
  symbols: string[];
  freq: string;
  status: BacktestRunStatus;
  initial_cash: number;
  final_cash: number | null;
  final_equity: number | null;
  benchmark_final_equity: number | null;
  created_at: string;
  completed_at: string | null;
  updated_at: string;
}

export interface BacktestRunDetail extends BacktestRunSummary {
  config_fingerprint: string;
  config: Record<string, unknown>;
  start_at: string;
  end_at: string;
  error_message: string | null;
}

export interface BacktestEquityPoint {
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

export interface BacktestEquityCurveResponse {
  points: BacktestEquityPoint[];
  total_points: number;
}

export interface BacktestMetrics {
  run_id: string;
  total_return: number | null;
  log_return: number | null;
  annualized_return: number | null;
  annualized_volatility: number | null;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  calmar_ratio: number | null;
  max_drawdown: number | null;
  max_drawdown_duration: number | null;
  total_fees: number | null;
  total_turnover: number | null;
  turnover_rate: number | null;
  total_trades: number | null;
  n_bars: number | null;
  risk_free_rate: number | null;
  trading_days_per_year: number | null;
  metrics_json: Record<string, unknown>;
  created_at: string;
}

export interface BacktestPosition {
  run_id: string;
  symbol: string;
  qty: number;
  position_json: Record<string, unknown>;
  created_at: string;
}

export interface BacktestPositionsResponse {
  list: BacktestPosition[];
}

export interface BacktestArtifact {
  id: string;
  run_id: string;
  artifact_type: string;
  uri: string;
  checksum: string | null;
  meta: Record<string, unknown>;
  created_at: string;
}

export interface BacktestArtifactsResponse {
  list: BacktestArtifact[];
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export function getBacktestRun(runId: string): Promise<BacktestRunDetail> {
  return apiFetch<ApiResponse<BacktestRunDetail>>(
    `/backtest-runs/${encodeURIComponent(runId)}`,
  ).then((res) => res.data);
}

export function getBacktestRunEquityCurve(
  runId: string,
): Promise<BacktestEquityCurveResponse> {
  return apiFetch<ApiResponse<BacktestEquityCurveResponse>>(
    `/backtest-runs/${encodeURIComponent(runId)}/equity-curve`,
  ).then((res) => res.data);
}

export function getBacktestRunMetrics(runId: string): Promise<BacktestMetrics> {
  return apiFetch<ApiResponse<BacktestMetrics>>(
    `/backtest-runs/${encodeURIComponent(runId)}/metrics`,
  ).then((res) => res.data);
}

export function getBacktestRunPositions(
  runId: string,
): Promise<BacktestPositionsResponse> {
  return apiFetch<ApiResponse<BacktestPositionsResponse>>(
    `/backtest-runs/${encodeURIComponent(runId)}/positions`,
  ).then((res) => res.data);
}

export function getBacktestRunArtifacts(
  runId: string,
): Promise<BacktestArtifactsResponse> {
  return apiFetch<ApiResponse<BacktestArtifactsResponse>>(
    `/backtest-runs/${encodeURIComponent(runId)}/artifacts`,
  ).then((res) => res.data);
}

/**
 * Download the binary content of a backtest artifact and trigger a save
 * dialog in the browser. The backend enforces owner-scope and path-traversal
 * protection; on the client this is a best-effort helper that follows the
 * standard pattern of fetch → blob → temporary anchor.
 *
 * The returned promise resolves once the download has been triggered; the
 * actual save is handled by the browser asynchronously.
 */
export async function downloadBacktestRunArtifact(
  runId: string,
  artifactId: string,
  filename: string,
): Promise<void> {
  const path =
    `/backtest-runs/${encodeURIComponent(runId)}` +
    `/artifacts/${encodeURIComponent(artifactId)}/content`;
  const res = await _fetchWithAuth(path, {
    headers: { Accept: "application/octet-stream" },
  });
  if (!res.ok) {
    // Mirror apiFetch's error shape: surface the status and a best-effort
    // body. For 4xx the body is JSON; for 5xx it may be empty.
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { message?: string; detail?: string };
      detail = body.message ?? body.detail ?? detail;
    } catch {
      /* ignore parse failures */
    }
    throw new ApiClientError(res.status, detail);
  }

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}
