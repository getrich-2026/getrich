import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { CSSProperties, ReactNode } from "react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { streamBacktestWalkForwardEvents } from "../../api/backtestJobEvents";
import { ApiClientError } from "../../api/client";
import { cancelBacktestJob } from "../../api/backtests";
import type { DrawdownPoint, EquityPoint } from "../../api/strategies";
import {
  getBacktestWalkForward,
  getBacktestWalkForwardOosEquityCurve,
  listBacktestWalkForwardWindows,
  type BacktestWalkForwardDetail as BacktestWalkForwardDetailData,
  type BacktestWalkForwardEquityPoint,
  type BacktestWalkForwardStatus,
  type BacktestWalkForwardWindow,
  type BacktestWalkForwardWindowStatus,
} from "../../api/backtestWalkForwards";
import EquityCurveChart from "../../components/EquityCurveChart";

const WINDOW_PAGE_SIZE = 20;

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

function fmtNum(value: number | null | undefined, digits = 4): string {
  if (value === null || value === undefined) return "—";
  return value.toFixed(digits);
}

function fmtInt(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return String(value);
}

function fmtBool(value: boolean | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value ? "Yes" : "No";
}

function compactJson(value: Record<string, unknown>): string {
  return JSON.stringify(value);
}

function formatJson(value: Record<string, unknown>): string {
  return JSON.stringify(value, null, 2);
}

function statusBadge(
  status: BacktestWalkForwardStatus | BacktestWalkForwardWindowStatus,
) {
  const map: Record<
    BacktestWalkForwardStatus | BacktestWalkForwardWindowStatus,
    { bg: string; fg: string }
  > = {
    queued: { bg: "var(--muted)", fg: "var(--muted-foreground)" },
    running: { bg: "var(--primary)", fg: "var(--primary-foreground)" },
    completed: { bg: "var(--success)", fg: "#fff" },
    failed: { bg: "var(--danger)", fg: "#fff" },
    cancelled: { bg: "var(--muted)", fg: "var(--muted-foreground)" },
  };
  const c = map[status];
  return (
    <span
      style={{
        padding: "3px 10px",
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 700,
        backgroundColor: c.bg,
        color: c.fg,
      }}
    >
      {status.toUpperCase()}
    </span>
  );
}

function MetricRow({
  label,
  value,
  mono,
}: {
  label: string;
  value: ReactNode;
  mono?: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        gap: 16,
        padding: "7px 0",
        borderBottom: "1px solid var(--border)",
        fontSize: 13,
      }}
    >
      <span className="text-muted">{label}</span>
      <span
        style={{
          fontFamily: mono ? "var(--font-mono, monospace)" : undefined,
          textAlign: "right",
        }}
      >
        {value}
      </span>
    </div>
  );
}

function SectionError({ error }: { error: unknown }) {
  return (
    <div className="error-box">
      {error instanceof Error ? error.message : "Failed to load section"}
    </div>
  );
}

function ProgressBar({ value }: { value: number }) {
  const safeValue = Math.max(0, Math.min(100, value));
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <div
        style={{
          flex: 1,
          height: 10,
          borderRadius: 999,
          background: "var(--muted)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${safeValue}%`,
            height: "100%",
            background: safeValue >= 100 ? "var(--success)" : "var(--primary)",
            transition: "width 0.2s ease",
          }}
        />
      </div>
      <span style={{ fontSize: 13, fontWeight: 600, minWidth: 46, textAlign: "right" }}>
        {safeValue.toFixed(0)}%
      </span>
    </div>
  );
}

const preStyle: CSSProperties = {
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
  fontSize: 12,
  lineHeight: 1.6,
  padding: 12,
  borderRadius: "var(--radius)",
  background: "var(--background)",
  border: "1px solid var(--border)",
};

function RunLink({ runId }: { runId: string | null }) {
  if (!runId) return <>—</>;
  return (
    <Link to={`/backtest-runs/${encodeURIComponent(runId)}`} style={{ fontSize: 13 }}>
      {runId}
    </Link>
  );
}

function SweepLink({ sweepId }: { sweepId: string | null }) {
  if (!sweepId) return <>—</>;
  return (
    <Link to={`/backtest-sweeps/${encodeURIComponent(sweepId)}`} style={{ fontSize: 13 }}>
      {sweepId}
    </Link>
  );
}

function toEquityChartData(points: BacktestWalkForwardEquityPoint[]): EquityPoint[] {
  const first = points.find((point) => point.equity > 0)?.equity;
  return points.map((point, index) => {
    const previous = index > 0 ? points[index - 1] : undefined;
    const dailyReturn = previous && previous.equity !== 0
      ? point.equity / previous.equity - 1
      : 0;
    return {
      date: point.dt,
      nav: point.equity,
      cumulative_return: first && first !== 0 ? point.equity / first - 1 : 0,
      daily_return: dailyReturn,
      position_ratio: point.gross_exposure ?? 0,
    };
  });
}

function toDrawdownData(points: BacktestWalkForwardEquityPoint[]): DrawdownPoint[] {
  let highWaterMark = Number.NEGATIVE_INFINITY;
  return points.map((point) => {
    highWaterMark = Math.max(highWaterMark, point.equity);
    const drawdown = highWaterMark > 0 ? point.equity / highWaterMark - 1 : 0;
    return { date: point.dt, drawdown };
  });
}

function OosEquityCurveCard({
  points,
  isLoading,
  error,
}: {
  points: BacktestWalkForwardEquityPoint[] | undefined;
  isLoading: boolean;
  error: unknown;
}) {
  const chartData = points ? toEquityChartData(points) : [];
  const drawdownData = points ? toDrawdownData(points) : [];
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h2 style={{ fontSize: 16, marginBottom: 12 }}>OOS Equity Curve</h2>
      {isLoading && <div className="loading">Loading OOS equity curve…</div>}
      {error ? <SectionError error={error} /> : null}
      {!isLoading && !error && chartData.length > 0 && (
        <EquityCurveChart equity={chartData} drawdown={drawdownData} />
      )}
      {!isLoading && !error && chartData.length === 0 && (
        <div className="text-muted" style={{ textAlign: "center", padding: 48 }}>
          No OOS equity data available for this walk-forward study.
        </div>
      )}
    </div>
  );
}

function WindowsTable({ windows }: { windows: BacktestWalkForwardWindow[] }) {
  if (windows.length === 0) {
    return (
      <div className="text-muted" style={{ textAlign: "center", padding: 24 }}>
        No windows recorded for this walk-forward study.
      </div>
    );
  }

  return (
    <div style={{ overflowX: "auto" }}>
      <table>
        <thead>
          <tr>
            <th>Index</th>
            <th>Status</th>
            <th>Train</th>
            <th>Validation</th>
            <th>Train Metric</th>
            <th>Validation Metric</th>
            <th>Train Sweep</th>
            <th>Best Run</th>
            <th>Validation Run</th>
            <th>Best Params</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody>
          {windows.map((windowRow) => {
            const paramsJson = compactJson(windowRow.best_params);
            return (
              <tr key={`${windowRow.walk_forward_id}-${windowRow.window_index}`}>
                <td>{windowRow.window_index}</td>
                <td>{statusBadge(windowRow.status)}</td>
                <td style={{ fontSize: 12 }}>
                  {fmtDate(windowRow.train_start)} — {fmtDate(windowRow.train_end)}
                </td>
                <td style={{ fontSize: 12 }}>
                  {fmtDate(windowRow.val_start)} — {fmtDate(windowRow.val_end)}
                </td>
                <td>{fmtNum(windowRow.train_metric_value)}</td>
                <td>{fmtNum(windowRow.validation_metric_value)}</td>
                <td style={{ fontFamily: "monospace", fontSize: 12 }}>
                  <SweepLink sweepId={windowRow.train_sweep_id} />
                </td>
                <td style={{ fontFamily: "monospace", fontSize: 12 }}>
                  <RunLink runId={windowRow.best_run_id} />
                </td>
                <td style={{ fontFamily: "monospace", fontSize: 12 }}>
                  <RunLink runId={windowRow.validation_run_id} />
                </td>
                <td
                  style={{
                    fontFamily: "monospace",
                    fontSize: 12,
                    maxWidth: 300,
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                  title={paramsJson}
                >
                  {paramsJson}
                </td>
                <td
                  style={{
                    maxWidth: 260,
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                  title={windowRow.error_message ?? undefined}
                >
                  {windowRow.error_message ?? "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function PaginationControls({
  page,
  totalPages,
  hasMore,
  onPageChange,
}: {
  page: number;
  totalPages: number;
  hasMore: boolean;
  onPageChange: (page: number) => void;
}) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 16 }}>
      <button
        onClick={() => onPageChange(Math.max(0, page - 1))}
        disabled={page === 0}
        style={{
          padding: "6px 12px",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius)",
          background: "var(--card-bg)",
          cursor: page === 0 ? "not-allowed" : "pointer",
          fontSize: 13,
        }}
      >
        ← Previous
      </button>
      <span className="text-muted" style={{ fontSize: 13 }}>
        Page {page + 1} / {Math.max(1, totalPages)}
      </span>
      <button
        onClick={() => onPageChange(page + 1)}
        disabled={!hasMore}
        style={{
          padding: "6px 12px",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius)",
          background: "var(--card-bg)",
          cursor: hasMore ? "pointer" : "not-allowed",
          fontSize: 13,
        }}
      >
        Next →
      </button>
    </div>
  );
}

function SummaryJsonHints({ walkForward }: { walkForward: BacktestWalkForwardDetailData }) {
  const aggregateMetrics = walkForward.summary_json.aggregate_metrics;
  const hasAggregateMetrics =
    aggregateMetrics !== null && aggregateMetrics !== undefined && typeof aggregateMetrics === "object";

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h2 style={{ fontSize: 16, marginBottom: 12 }}>Validation Summary</h2>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 24 }}>
        <div>
          <MetricRow label="Mean Validation Metric" value={fmtNum(walkForward.mean_validation_metric)} />
          <MetricRow label="Select Metric" value={walkForward.select_metric || "—"} />
        </div>
        <div>
          <MetricRow label="Search Type" value={walkForward.search_type || "—"} />
          <MetricRow label="Refit" value={walkForward.refit || "—"} />
        </div>
      </div>
      {hasAggregateMetrics && (
        <div style={{ marginTop: 16 }}>
          <h3 style={{ fontSize: 14, marginBottom: 8 }}>Aggregate Metrics</h3>
          <pre style={preStyle}>{JSON.stringify(aggregateMetrics, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}

export default function BacktestWalkForwardDetail() {
  const { walkForwardId } = useParams<{ walkForwardId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [windowPage, setWindowPage] = useState(0);
  // SSE-driven: when the stream is healthy we don't poll. The 5 s
  // refetchInterval kicks in if the stream errors (network blip).
  const [sseActive, setSseActive] = useState(true);
  // Surface cancel API errors inline (the network is otherwise silent
  // because the cancel button replaces itself with a "Cancelling…"
  // disabled state).
  const [cancelError, setCancelError] = useState<string | null>(null);

  const {
    data: walkForward,
    isLoading: walkForwardLoading,
    error: walkForwardError,
  } = useQuery({
    queryKey: ["backtest-walk-forward", walkForwardId],
    queryFn: () => getBacktestWalkForward(walkForwardId!),
    enabled: !!walkForwardId,
    refetchInterval: sseActive
      ? false
      : (query) => {
          const current = query.state.data;
          if (!current) return false;
          const liveStatus = current.job_status ?? current.status;
          return liveStatus === "queued" || liveStatus === "running"
            ? 5000
            : false;
        },
  });

  const windowsQuery = useQuery({
    queryKey: ["backtest-walk-forward-windows", walkForwardId, windowPage],
    queryFn: () =>
      listBacktestWalkForwardWindows(walkForwardId!, {
        page: windowPage,
        page_size: WINDOW_PAGE_SIZE,
      }),
    enabled: !!walkForwardId,
  });

  const oosEquityQuery = useQuery({
    queryKey: ["backtest-walk-forward-oos-equity", walkForwardId],
    queryFn: () => getBacktestWalkForwardOosEquityCurve(walkForwardId!),
    enabled: !!walkForwardId,
  });

  // SSE: open a stream against the dedicated
  // /backtest-walk-forwards/{id}/events endpoint. The payload is a
  // full ``BacktestWalkForwardDetail`` (with the parent job's
  // progress / job_status merged in), so we can replace the cached
  // entry wholesale. The stream opens as soon as the page has a
  // ``walkForwardId`` — no need to wait for the runner to claim the
  // job. On `done` we invalidate the windows query so the
  // (now-final) walk-forward's window list + summary_json surface.
  useEffect(() => {
    if (!walkForwardId) return;
    const ctrl = streamBacktestWalkForwardEvents(walkForwardId, {
      onOpen: () => setSseActive(true),
      onEvent: (event) => {
        if (event.type === "error") return;
        // The wire payload IS the walk-forward detail. Drop it
        // straight into the cache; the field set is a superset of
        // the cached row.
        const payload = event.data as unknown as BacktestWalkForwardDetailData;
        queryClient.setQueryData(
          ["backtest-walk-forward", walkForwardId],
          payload,
        );
        if (event.type === "done") {
          void queryClient.invalidateQueries({
            queryKey: ["backtest-walk-forward-windows", walkForwardId],
          });
        }
      },
      onError: () => {
        setSseActive(false);
      },
    });
    return () => {
      ctrl.abort();
    };
  }, [walkForwardId, queryClient]);

  // Cancel the underlying backtest_jobs row. The walk-forward result
  // row is derived from the job, so flipping the job to ``cancelled``
  // is enough — the next SSE tick (or the polling fallback) will pick
  // up the new ``job_status`` and re-render the badge. Mirrors the
  // BacktestJobDetail pattern.
  const cancelMutation = useMutation({
    mutationFn: (id: string) => cancelBacktestJob(id),
    onSuccess: () => {
      setCancelError(null);
      void queryClient.invalidateQueries({
        queryKey: ["backtest-walk-forward", walkForwardId],
      });
      void queryClient.invalidateQueries({ queryKey: ["backtest-jobs"] });
    },
    onError: (err: unknown) => {
      setCancelError(err instanceof ApiClientError ? err.detail : "Cancel failed");
    },
  });

  const handleCancel = () => {
    if (!walkForward?.job_id) return;
    const ok = window.confirm(
      `Cancel walk-forward ${walkForward.walk_forward_id}? The runner will stop at the next window boundary.`,
    );
    if (!ok) return;
    setCancelError(null);
    cancelMutation.mutate(walkForward.job_id);
  };

  if (walkForwardLoading) {
    return (
      <div style={{ maxWidth: 1120, margin: "24px auto" }}>
        <div className="loading">Loading walk-forward result…</div>
      </div>
    );
  }

  if (walkForwardError || !walkForward) {
    return (
      <div style={{ maxWidth: 1120, margin: "24px auto" }}>
        <div className="error-box">
          {walkForwardError instanceof Error
            ? walkForwardError.message
            : "Backtest walk-forward study not found"}
        </div>
        <button
          onClick={() => navigate("/backtests")}
          style={{
            marginTop: 12,
            padding: "6px 16px",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius)",
            background: "var(--card-bg)",
            cursor: "pointer",
            fontSize: 13,
          }}
        >
          ← Back to Backtests
        </button>
      </div>
    );
  }

  const pagination = windowsQuery.data?.pagination;
  // Prefer the live job_status from the SSE channel over the
  // walk-forward's own (terminal) status when both are available.
  // This keeps the badge in sync with the runner before the result
  // row itself is updated.
  const liveStatus: BacktestWalkForwardStatus = (walkForward.job_status ??
    walkForward.status) as BacktestWalkForwardStatus;
  const liveProgress = walkForward.progress ?? 0;
  const showProgress = liveStatus === "queued" || liveStatus === "running";

  return (
    <div style={{ maxWidth: 1120, margin: "24px auto" }}>
      <div style={{ marginBottom: 16 }}>
        <Link to="/backtests" style={{ fontSize: 13 }}>
          ← Back to Backtests
        </Link>
      </div>

      <div className="card" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            gap: 16,
          }}
        >
          <div>
            <h1 className="section-title" style={{ marginBottom: 6 }}>
              Walk-forward Result
            </h1>
            <div style={{ fontFamily: "monospace", fontSize: 13 }}>
              {walkForward.walk_forward_id}
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {statusBadge(liveStatus)}
            {showProgress && (
              <button
                type="button"
                onClick={handleCancel}
                disabled={cancelMutation.isPending}
                data-testid="walk-forward-cancel-button"
                style={{
                  padding: "6px 12px",
                  border: "1px solid var(--danger)",
                  borderRadius: "var(--radius)",
                  background: "transparent",
                  color: "var(--danger)",
                  cursor: cancelMutation.isPending ? "not-allowed" : "pointer",
                  fontSize: 13,
                }}
              >
                {cancelMutation.isPending ? "Cancelling…" : "Cancel"}
              </button>
            )}
          </div>
        </div>
        {cancelError && (
          <div className="error-box" data-testid="walk-forward-cancel-error">
            {cancelError}
          </div>
        )}
        {showProgress && (
          <div data-testid="walk-forward-live-progress">
            <ProgressBar value={liveProgress} />
          </div>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 24 }}>
          <div>
            <MetricRow label="Search Type" value={walkForward.search_type || "—"} />
            <MetricRow label="Select Metric" value={walkForward.select_metric || "—"} />
            <MetricRow label="Maximize" value={fmtBool(walkForward.maximize)} />
            <MetricRow label="Refit" value={walkForward.refit || "—"} />
            <MetricRow label="Mean Validation Metric" value={fmtNum(walkForward.mean_validation_metric)} />
          </div>
          <div>
            <MetricRow label="Total Windows" value={fmtInt(walkForward.total_windows)} />
            <MetricRow label="Completed Windows" value={fmtInt(walkForward.completed_windows)} />
            <MetricRow label="Failed Windows" value={fmtInt(walkForward.failed_windows)} />
            <MetricRow label="Created" value={fmtDate(walkForward.created_at)} />
            <MetricRow label="Updated" value={fmtDate(walkForward.updated_at)} />
            <MetricRow label="Completed" value={fmtDate(walkForward.completed_at)} />
          </div>
        </div>
      </div>

      <SummaryJsonHints walkForward={walkForward} />

      <OosEquityCurveCard
        points={oosEquityQuery.data?.points}
        isLoading={oosEquityQuery.isLoading}
        error={oosEquityQuery.error}
      />

      <div className="card" style={{ marginTop: 16 }}>
        <h2 style={{ fontSize: 16, marginBottom: 12 }}>Windows</h2>
        {windowsQuery.isLoading && <div className="loading">Loading windows…</div>}
        {windowsQuery.error ? <SectionError error={windowsQuery.error} /> : null}
        {!windowsQuery.isLoading && !windowsQuery.error && (
          <>
            <WindowsTable windows={windowsQuery.data?.list ?? []} />
            {pagination && (
              <PaginationControls
                page={windowPage}
                totalPages={pagination.total_pages}
                hasMore={Boolean(pagination.has_more)}
                onPageChange={setWindowPage}
              />
            )}
          </>
        )}
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h2 style={{ fontSize: 16, marginBottom: 12 }}>Search Spec</h2>
        <pre style={preStyle}>{formatJson(walkForward.search_spec)}</pre>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h2 style={{ fontSize: 16, marginBottom: 12 }}>Summary JSON</h2>
        <pre style={preStyle}>{formatJson(walkForward.summary_json)}</pre>
      </div>
    </div>
  );
}
