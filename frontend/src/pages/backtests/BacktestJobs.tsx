import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useState } from "react";
import {
  cancelBacktestJob,
  listBacktestJobs,
  type BacktestJobStatus,
  type BacktestJobSummary,
  type BacktestJobType,
} from "../../api/backtests";
import { ApiClientError } from "../../api/client";

const PAGE_SIZE = 10;

const JOB_TYPE_OPTIONS: Array<{ value: BacktestJobType | "all"; label: string }> = [
  { value: "all", label: "All Types" },
  { value: "backtest", label: "Backtest" },
  { value: "sweep", label: "Sweep" },
  { value: "walk_forward", label: "Walk Forward" },
];

const STATUS_OPTIONS: Array<{ value: BacktestJobStatus | "all"; label: string }> = [
  { value: "all", label: "All Statuses" },
  { value: "queued", label: "Queued" },
  { value: "running", label: "Running" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];

function isActiveJob(status: BacktestJobStatus): boolean {
  return status === "queued" || status === "running";
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

function fmtJobType(type: BacktestJobType): string {
  if (type === "walk_forward") return "Walk Forward";
  return type.charAt(0).toUpperCase() + type.slice(1);
}

function statusBadge(status: BacktestJobStatus) {
  const map: Record<BacktestJobStatus, { bg: string; fg: string }> = {
    queued: { bg: "var(--warning)", fg: "#fff" },
    running: { bg: "var(--primary)", fg: "var(--primary-foreground)" },
    completed: { bg: "var(--success)", fg: "#fff" },
    failed: { bg: "var(--danger)", fg: "#fff" },
    cancelled: { bg: "var(--muted)", fg: "var(--muted-foreground)" },
  };
  const c = map[status];
  return (
    <span
      style={{
        padding: "2px 8px",
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 600,
        backgroundColor: c.bg,
        color: c.fg,
      }}
    >
      {status.toUpperCase()}
    </span>
  );
}

function ProgressBar({ value }: { value: number }) {
  const safeValue = Math.max(0, Math.min(100, value));
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 130 }}>
      <div
        style={{
          flex: 1,
          height: 8,
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
      <span style={{ fontSize: 12, minWidth: 38, textAlign: "right" }}>
        {safeValue.toFixed(0)}%
      </span>
    </div>
  );
}

function filterButtonStyle(active: boolean): React.CSSProperties {
  return {
    padding: "4px 12px",
    fontSize: 12,
    fontWeight: 500,
    border: "1px solid var(--border)",
    borderRadius: "var(--radius)",
    background: active ? "var(--primary)" : "var(--card-bg)",
    color: active ? "var(--primary-foreground)" : "var(--foreground)",
    cursor: "pointer",
  };
}

function requestStrategy(job: BacktestJobSummary): string {
  return job.ref_id || "—";
}

export default function BacktestJobs() {
  const queryClient = useQueryClient();
  const [jobType, setJobType] = useState<BacktestJobType | "all">("all");
  const [status, setStatus] = useState<BacktestJobStatus | "all">("all");
  const [page, setPage] = useState(0);
  const [cancelError, setCancelError] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["backtest-jobs", jobType, status, page],
    queryFn: () =>
      listBacktestJobs({
        job_type: jobType === "all" ? undefined : jobType,
        status: status === "all" ? undefined : status,
        page,
        page_size: PAGE_SIZE,
      }),
    refetchInterval: (query) => {
      const jobs = query.state.data?.list ?? [];
      return jobs.some((job) => isActiveJob(job.status)) ? 5000 : false;
    },
  });

  const jobs = data?.list ?? [];
  const pagination = data?.pagination;
  const totalPages = pagination?.total_pages ?? 0;

  const cancelMutation = useMutation({
    mutationFn: (jobId: string) => cancelBacktestJob(jobId),
    onSuccess: () => {
      setCancelError(null);
      queryClient.invalidateQueries({ queryKey: ["backtest-jobs"] });
    },
    onError: (err: unknown) => {
      setCancelError(err instanceof ApiClientError ? err.detail : "Cancel failed");
    },
  });

  const handleCancel = (job: BacktestJobSummary) => {
    const ok = window.confirm(`Cancel backtest job ${job.job_id}?`);
    if (!ok) return;
    setCancelError(null);
    cancelMutation.mutate(job.job_id);
  };

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 16,
          marginBottom: 16,
        }}
      >
        <div>
          <h1 className="section-title" style={{ marginBottom: 4 }}>
            Backtest Jobs
          </h1>
          <p className="text-muted" style={{ fontSize: 13 }}>
            Submit backtests, monitor progress, and cancel queued or running jobs.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Link
            to="/backtests/new-walk-forward"
            style={{
              padding: "8px 14px",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              color: "var(--foreground)",
              textDecoration: "none",
              fontSize: 13,
              fontWeight: 600,
            }}
          >
            New Walk-forward
          </Link>
          <Link
            to="/backtests/new-sweep"
            style={{
              padding: "8px 14px",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              color: "var(--foreground)",
              textDecoration: "none",
              fontSize: 13,
              fontWeight: 600,
            }}
          >
            New Sweep
          </Link>
          <Link
            to="/backtests/new"
            style={{
              padding: "8px 14px",
              borderRadius: "var(--radius)",
              background: "var(--primary)",
              color: "var(--primary-foreground)",
              textDecoration: "none",
              fontSize: 13,
              fontWeight: 600,
            }}
          >
            New Backtest
          </Link>
        </div>
      </div>

      <div style={{ marginBottom: 12, display: "flex", gap: 6, flexWrap: "wrap" }}>
        {JOB_TYPE_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            onClick={() => {
              setJobType(opt.value);
              setPage(0);
            }}
            style={filterButtonStyle(jobType === opt.value)}
          >
            {opt.label}
          </button>
        ))}
      </div>
      <div style={{ marginBottom: 16, display: "flex", gap: 6, flexWrap: "wrap" }}>
        {STATUS_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            onClick={() => {
              setStatus(opt.value);
              setPage(0);
            }}
            style={filterButtonStyle(status === opt.value)}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {cancelError && <div className="error-box" style={{ marginBottom: 16 }}>{cancelError}</div>}
      {isLoading && <div className="loading">Loading backtest jobs…</div>}
      {error && (
        <div className="error-box">
          {error instanceof Error ? error.message : "Unknown error"}
        </div>
      )}

      {data && jobs.length === 0 && (
        <div className="card">
          <div className="text-muted" style={{ textAlign: "center", padding: 24 }}>
            No backtest jobs found.
          </div>
        </div>
      )}

      {data && jobs.length > 0 && (
        <div className="card" style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>Job ID</th>
                <th>Type</th>
                <th>Status</th>
                <th>Ref ID</th>
                <th>Progress</th>
                <th>Created</th>
                <th>Updated / Completed</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.job_id}>
                  <td style={{ fontFamily: "monospace", fontSize: 12 }} title={job.job_id}>
                    {job.job_id.slice(0, 12)}…
                  </td>
                  <td>{fmtJobType(job.job_type)}</td>
                  <td>{statusBadge(job.status)}</td>
                  <td style={{ fontFamily: "monospace", fontSize: 12 }} title={job.ref_id}>
                    {requestStrategy(job)}
                  </td>
                  <td><ProgressBar value={job.progress} /></td>
                  <td style={{ fontSize: 12 }}>{fmtDate(job.created_at)}</td>
                  <td style={{ fontSize: 12 }}>
                    {fmtDate(job.completed_at ?? job.updated_at)}
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <Link to={`/backtests/${encodeURIComponent(job.job_id)}`} style={{ fontSize: 12 }}>
                        View
                      </Link>
                      {isActiveJob(job.status) && (
                        <button
                          onClick={() => handleCancel(job)}
                          disabled={cancelMutation.isPending}
                          style={{
                            padding: "3px 8px",
                            border: "1px solid var(--danger)",
                            borderRadius: "var(--radius)",
                            background: "transparent",
                            color: "var(--danger)",
                            cursor: cancelMutation.isPending ? "not-allowed" : "pointer",
                            fontSize: 12,
                          }}
                        >
                          Cancel
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {totalPages > 1 && (
        <div className="pagination" style={{ marginTop: 16 }}>
          <button disabled={page === 0} onClick={() => setPage(page - 1)}>
            Previous
          </button>
          {Array.from({ length: totalPages }, (_, i) => (
            <button
              key={i}
              className={i === page ? "active" : ""}
              onClick={() => setPage(i)}
            >
              {i + 1}
            </button>
          ))}
          <button disabled={page >= totalPages - 1} onClick={() => setPage(page + 1)}>
            Next
          </button>
        </div>
      )}
    </div>
  );
}
