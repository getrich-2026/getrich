import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { CSSProperties, ReactNode } from "react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { streamBacktestSweepEvents } from "../../api/backtestJobEvents";
import { ApiClientError } from "../../api/client";
import { cancelBacktestJob } from "../../api/backtests";
import {
  getBacktestSweep,
  listBacktestSweepTrials,
  type BacktestSweepDetail as BacktestSweepDetailData,
  type BacktestSweepStatus,
  type BacktestSweepTrial,
  type BacktestSweepTrialStatus,
} from "../../api/backtestSweeps";

const TRIAL_PAGE_SIZE = 20;

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

function recordValue(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

function statusBadge(status: BacktestSweepStatus | BacktestSweepTrialStatus) {
  const map: Record<
    BacktestSweepStatus | BacktestSweepTrialStatus,
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

function BestTrialCard({ sweep }: { sweep: BacktestSweepDetailData }) {
  const bestParams = recordValue(sweep.summary_json.best_params);
  if (!sweep.best_trial_id && !sweep.best_run_id && !bestParams) {
    return (
      <div className="card" style={{ marginTop: 16 }}>
        <h2 style={{ fontSize: 16, marginBottom: 12 }}>Best Trial</h2>
        <div className="text-muted" style={{ textAlign: "center", padding: 24 }}>
          No best trial recorded for this sweep.
        </div>
      </div>
    );
  }

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h2 style={{ fontSize: 16, marginBottom: 12 }}>Best Trial</h2>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 24 }}>
        <div>
          <MetricRow label="Best Trial ID" value={sweep.best_trial_id || "—"} mono />
          <MetricRow label="Best Run ID" value={<RunLink runId={sweep.best_run_id} />} mono />
        </div>
        <div>
          <MetricRow label="Select Metric" value={sweep.select_metric || "—"} />
          <MetricRow label="Best Metric Value" value={fmtNum(sweep.best_metric_value)} />
        </div>
      </div>
      <div style={{ marginTop: 16 }}>
        <h3 style={{ fontSize: 14, marginBottom: 8 }}>Best Params</h3>
        {bestParams ? (
          <pre style={preStyle}>{formatJson(bestParams)}</pre>
        ) : (
          <div className="text-muted" style={{ padding: 12 }}>
            No best params recorded.
          </div>
        )}
      </div>
    </div>
  );
}

function TrialsTable({ trials }: { trials: BacktestSweepTrial[] }) {
  if (trials.length === 0) {
    return (
      <div className="text-muted" style={{ textAlign: "center", padding: 24 }}>
        No trials recorded for this sweep.
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
            <th>Select Metric</th>
            <th>Run</th>
            <th>Params</th>
            <th>Error</th>
            <th>Completed</th>
          </tr>
        </thead>
        <tbody>
          {trials.map((trial) => {
            const paramsJson = compactJson(trial.params);
            return (
              <tr key={trial.trial_id}>
                <td>{trial.trial_index}</td>
                <td>{statusBadge(trial.status)}</td>
                <td>{fmtNum(trial.select_metric_value)}</td>
                <td style={{ fontFamily: "monospace", fontSize: 12 }}>
                  <RunLink runId={trial.run_id} />
                </td>
                <td
                  style={{
                    fontFamily: "monospace",
                    fontSize: 12,
                    maxWidth: 340,
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
                    maxWidth: 300,
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                  title={trial.error_message ?? undefined}
                >
                  {trial.error_message ?? "—"}
                </td>
                <td style={{ fontSize: 12 }}>{fmtDate(trial.completed_at)}</td>
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

export default function BacktestSweepDetail() {
  const { sweepId } = useParams<{ sweepId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [trialPage, setTrialPage] = useState(0);
  // SSE-driven: when the stream is healthy we don't poll. The 5 s
  // refetchInterval kicks in if the stream errors (network blip).
  const [sseActive, setSseActive] = useState(true);
  // Surface cancel API errors inline (the network is otherwise silent
  // because the cancel button replaces itself with a "Cancelling…"
  // disabled state).
  const [cancelError, setCancelError] = useState<string | null>(null);

  const {
    data: sweep,
    isLoading: sweepLoading,
    error: sweepError,
  } = useQuery({
    queryKey: ["backtest-sweep", sweepId],
    queryFn: () => getBacktestSweep(sweepId!),
    enabled: !!sweepId,
    refetchInterval: sseActive
      ? false
      : (query) => {
          const current = query.state.data;
          if (!current) return false;
          // Fall back to polling only when the job is still in flight
          // — once the sweep row is terminal there's nothing to
          // update until the user navigates.
          const liveStatus = current.job_status ?? current.status;
          return liveStatus === "queued" || liveStatus === "running"
            ? 5000
            : false;
        },
  });

  const trialsQuery = useQuery({
    queryKey: ["backtest-sweep-trials", sweepId, trialPage],
    queryFn: () =>
      listBacktestSweepTrials(sweepId!, {
        page: trialPage,
        page_size: TRIAL_PAGE_SIZE,
      }),
    enabled: !!sweepId,
  });

  // SSE: open a stream against the dedicated /backtest-sweeps/{id}/events
  // endpoint. The payload is a full ``BacktestSweepDetail`` (with the
  // parent job's progress / job_status merged in), so we can replace
  // the cached entry wholesale. The stream opens as soon as the page
  // has a ``sweepId`` — no need to wait for the runner to claim the
  // job. On `done` we invalidate the trials query so the (now-final)
  // sweep's trial list + best_run_id surface.
  useEffect(() => {
    if (!sweepId) return;
    const ctrl = streamBacktestSweepEvents(sweepId, {
      onOpen: () => setSseActive(true),
      onEvent: (event) => {
        if (event.type === "error") return;
        // The wire payload IS the sweep detail. Drop it straight into
        // the cache; the field set is a superset of the cached row.
        const payload = event.data as unknown as BacktestSweepDetailData;
        queryClient.setQueryData(["backtest-sweep", sweepId], payload);
        if (event.type === "done") {
          void queryClient.invalidateQueries({
            queryKey: ["backtest-sweep-trials", sweepId],
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
  }, [sweepId, queryClient]);

  // Cancel the underlying backtest_jobs row. The result sweep / walk-
  // forward rows are derived from the job, so flipping the job to
  // ``cancelled`` is enough — the next SSE tick (or the polling
  // fallback) will pick up the new ``job_status`` and re-render the
  // badge. Mirrors the BacktestJobDetail pattern.
  const cancelMutation = useMutation({
    mutationFn: (id: string) => cancelBacktestJob(id),
    onSuccess: () => {
      setCancelError(null);
      void queryClient.invalidateQueries({ queryKey: ["backtest-sweep", sweepId] });
      void queryClient.invalidateQueries({ queryKey: ["backtest-jobs"] });
    },
    onError: (err: unknown) => {
      setCancelError(err instanceof ApiClientError ? err.detail : "Cancel failed");
    },
  });

  const handleCancel = () => {
    if (!sweep?.job_id) return;
    const ok = window.confirm(
      `Cancel sweep ${sweep.sweep_id}? The runner will stop at the next trial boundary.`,
    );
    if (!ok) return;
    setCancelError(null);
    cancelMutation.mutate(sweep.job_id);
  };

  if (sweepLoading) {
    return (
      <div style={{ maxWidth: 980, margin: "24px auto" }}>
        <div className="loading">Loading sweep result…</div>
      </div>
    );
  }

  if (sweepError || !sweep) {
    return (
      <div style={{ maxWidth: 980, margin: "24px auto" }}>
        <div className="error-box">
          {sweepError instanceof Error ? sweepError.message : "Backtest sweep not found"}
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

  const pagination = trialsQuery.data?.pagination;
  // Prefer the live job_status from the SSE channel over the
  // sweep's own (terminal) status when both are available. This
  // keeps the badge in sync with the runner before the sweep row
  // itself is updated.
  const liveStatus: BacktestSweepStatus = (sweep.job_status ??
    sweep.status) as BacktestSweepStatus;
  const liveProgress = sweep.progress ?? 0;
  const showProgress = liveStatus === "queued" || liveStatus === "running";

  return (
    <div style={{ maxWidth: 980, margin: "24px auto" }}>
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
              Sweep Result
            </h1>
            <div style={{ fontFamily: "monospace", fontSize: 13 }}>{sweep.sweep_id}</div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {statusBadge(liveStatus)}
            {showProgress && (
              <button
                type="button"
                onClick={handleCancel}
                disabled={cancelMutation.isPending}
                data-testid="sweep-cancel-button"
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
          <div className="error-box" data-testid="sweep-cancel-error">
            {cancelError}
          </div>
        )}
        {showProgress && (
          <div data-testid="sweep-live-progress">
            <ProgressBar value={liveProgress} />
          </div>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 24 }}>
          <div>
            <MetricRow label="Search Type" value={sweep.search_type || "—"} />
            <MetricRow label="Select Metric" value={sweep.select_metric || "—"} />
            <MetricRow label="Maximize" value={fmtBool(sweep.maximize)} />
            <MetricRow label="Best Metric Value" value={fmtNum(sweep.best_metric_value)} />
            <MetricRow label="Best Trial ID" value={sweep.best_trial_id || "—"} mono />
            <MetricRow label="Best Run ID" value={<RunLink runId={sweep.best_run_id} />} mono />
          </div>
          <div>
            <MetricRow label="Total Trials" value={fmtInt(sweep.total_trials)} />
            <MetricRow label="Completed Trials" value={fmtInt(sweep.completed_trials)} />
            <MetricRow label="Failed Trials" value={fmtInt(sweep.failed_trials)} />
            <MetricRow label="Created" value={fmtDate(sweep.created_at)} />
            <MetricRow label="Updated" value={fmtDate(sweep.updated_at)} />
            <MetricRow label="Completed" value={fmtDate(sweep.completed_at)} />
          </div>
        </div>
      </div>

      <BestTrialCard sweep={sweep} />

      <div className="card" style={{ marginTop: 16 }}>
        <h2 style={{ fontSize: 16, marginBottom: 12 }}>Search Spec</h2>
        <pre style={preStyle}>{formatJson(sweep.search_spec)}</pre>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h2 style={{ fontSize: 16, marginBottom: 12 }}>Trials</h2>
        {trialsQuery.isLoading && <div className="loading">Loading trials…</div>}
        {trialsQuery.error ? <SectionError error={trialsQuery.error} /> : null}
        {!trialsQuery.isLoading && !trialsQuery.error && (
          <>
            <TrialsTable trials={trialsQuery.data?.list ?? []} />
            {pagination && (
              <PaginationControls
                page={trialPage}
                totalPages={pagination.total_pages}
                hasMore={Boolean(pagination.has_more)}
                onPageChange={setTrialPage}
              />
            )}
          </>
        )}
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h2 style={{ fontSize: 16, marginBottom: 12 }}>Summary JSON</h2>
        <pre style={preStyle}>{formatJson(sweep.summary_json)}</pre>
      </div>
    </div>
  );
}
