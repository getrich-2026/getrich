import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  cancelBacktestJob,
  getBacktestJob,
  type BacktestJobDetail as BacktestJobDetailData,
  type BacktestJobStatus,
  type BacktestJobType,
} from "../../api/backtests";
import { streamBacktestJobEvents } from "../../api/backtestJobEvents";
import { ApiClientError } from "../../api/client";
import { useEffect, useState } from "react";

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

function MetricRow({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
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
      <span style={{ fontFamily: mono ? "var(--font-mono, monospace)" : undefined }}>
        {value}
      </span>
    </div>
  );
}

function redactRequestJson(requestJson: Record<string, unknown>): Record<string, unknown> {
  const redacted: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(requestJson)) {
    if (key === "_idempotency_key" || key === "_user_id") {
      redacted[key] = "<redacted>";
    } else {
      redacted[key] = value;
    }
  }
  return redacted;
}

function ResultHint({ job }: { job: BacktestJobDetailData }) {
  if (job.status !== "completed" || !job.ref_id) return null;

  if (job.job_type === "backtest") {
    return (
      <div className="card" style={{ marginTop: 16 }}>
        <h2 style={{ fontSize: 16, marginBottom: 8 }}>Backtest run result</h2>
        <p className="text-muted" style={{ fontSize: 13, lineHeight: 1.6 }}>
          Result reference <code>{job.ref_id}</code> is ready.
        </p>
        <Link
          to={`/backtest-runs/${encodeURIComponent(job.ref_id)}`}
          style={{ fontSize: 13, fontWeight: 600 }}
        >
          View Run Result →
        </Link>
      </div>
    );
  }

  if (job.job_type === "sweep") {
    return (
      <div className="card" style={{ marginTop: 16 }}>
        <h2 style={{ fontSize: 16, marginBottom: 8 }}>Sweep result</h2>
        <p className="text-muted" style={{ fontSize: 13, lineHeight: 1.6 }}>
          Result reference <code>{job.ref_id}</code> is ready.
        </p>
        <Link
          to={`/backtest-sweeps/${encodeURIComponent(job.ref_id)}`}
          style={{ fontSize: 13, fontWeight: 600 }}
        >
          View Sweep Result →
        </Link>
      </div>
    );
  }

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h2 style={{ fontSize: 16, marginBottom: 8 }}>Walk-forward result</h2>
      <p className="text-muted" style={{ fontSize: 13, lineHeight: 1.6 }}>
        Result reference <code>{job.ref_id}</code> is ready.
      </p>
      <Link
        to={`/backtest-walk-forwards/${encodeURIComponent(job.ref_id)}`}
        style={{ fontSize: 13, fontWeight: 600 }}
      >
        View Walk-forward Result →
      </Link>
    </div>
  );
}

export default function BacktestJobDetail() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [cancelError, setCancelError] = useState<string | null>(null);
  // SSE-driven: when the stream is healthy we don't poll. When the
  // stream errors (network blip, server 5xx, etc.) we flip back to the
  // legacy 5 s `refetchInterval` so the page keeps working.
  const [sseActive, setSseActive] = useState(true);

  const {
    data: job,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["backtest-job", jobId],
    queryFn: () => getBacktestJob(jobId!),
    enabled: !!jobId,
    refetchInterval: sseActive
      ? false
      : (query) => {
          const current = query.state.data;
          return current && isActiveJob(current.status) ? 5000 : false;
        },
  });

  // SSE: open a stream when the page mounts / jobId changes. Each
  // event merges into the existing `useQuery` data via setQueryData,
  // so the rest of the page (status badge, progress bar, cancel
  // button, etc.) keeps working without further refactors.
  useEffect(() => {
    if (!jobId) return;
    const ctrl = streamBacktestJobEvents(jobId, {
      onOpen: () => setSseActive(true),
      onEvent: (event) => {
        if (event.type === "error") return;
        queryClient.setQueryData(
          ["backtest-job", jobId],
          (prev: BacktestJobDetailData | undefined) => event.data ?? prev,
        );
      },
      onError: () => {
        setSseActive(false);
      },
    });
    return () => {
      ctrl.abort();
    };
  }, [jobId, queryClient]);

  const cancelMutation = useMutation({
    mutationFn: (id: string) => cancelBacktestJob(id),
    onSuccess: () => {
      setCancelError(null);
      queryClient.invalidateQueries({ queryKey: ["backtest-job", jobId] });
      queryClient.invalidateQueries({ queryKey: ["backtest-jobs"] });
    },
    onError: (err: unknown) => {
      setCancelError(err instanceof ApiClientError ? err.detail : "Cancel failed");
    },
  });

  const handleCancel = () => {
    if (!job) return;
    const ok = window.confirm(`Cancel backtest job ${job.job_id}?`);
    if (!ok) return;
    setCancelError(null);
    cancelMutation.mutate(job.job_id);
  };

  if (isLoading) {
    return (
      <div style={{ maxWidth: 860, margin: "24px auto" }}>
        <div className="loading">Loading backtest job…</div>
      </div>
    );
  }

  if (error || !job) {
    return (
      <div style={{ maxWidth: 860, margin: "24px auto" }}>
        <div className="error-box">
          {error instanceof Error ? error.message : "Backtest job not found"}
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

  const redactedRequest = redactRequestJson(job.request_json);

  return (
    <div style={{ maxWidth: 860, margin: "24px auto" }}>
      <div style={{ marginBottom: 16 }}>
        <Link to="/backtests" style={{ fontSize: 13 }}>
          ← Back to Backtests
        </Link>
      </div>

      <div
        className="card"
        style={{ display: "flex", flexDirection: "column", gap: 16, marginBottom: 16 }}
      >
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
              {fmtJobType(job.job_type)} Job
            </h1>
            <div style={{ fontFamily: "monospace", fontSize: 13 }}>{job.job_id}</div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {statusBadge(job.status)}
            {isActiveJob(job.status) && (
              <button
                onClick={handleCancel}
                disabled={cancelMutation.isPending}
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
                Cancel
              </button>
            )}
          </div>
        </div>

        {cancelError && <div className="error-box">{cancelError}</div>}

        <ProgressBar value={job.progress} />

        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 24 }}>
          <div>
            <MetricRow label="Type" value={fmtJobType(job.job_type)} />
            <MetricRow label="Status" value={job.status} />
            <MetricRow label="Ref ID" value={job.ref_id || "—"} mono />
            <MetricRow label="Progress" value={`${Math.max(0, Math.min(100, job.progress)).toFixed(0)}%`} />
          </div>
          <div>
            <MetricRow label="Created" value={fmtDate(job.created_at)} />
            <MetricRow label="Started" value={fmtDate(job.started_at)} />
            <MetricRow label="Updated" value={fmtDate(job.updated_at)} />
            <MetricRow label="Completed" value={fmtDate(job.completed_at)} />
          </div>
        </div>
      </div>

      {job.error_message && (
        <div className="error-box" style={{ marginBottom: 16 }}>
          {job.error_message}
        </div>
      )}

      <ResultHint job={job} />

      <div className="card" style={{ marginTop: 16 }}>
        <h2 style={{ fontSize: 16, marginBottom: 12 }}>Request JSON</h2>
        <pre
          style={{
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            fontSize: 12,
            lineHeight: 1.6,
            padding: 12,
            borderRadius: "var(--radius)",
            background: "var(--background)",
            border: "1px solid var(--border)",
          }}
        >
          {JSON.stringify(redactedRequest, null, 2)}
        </pre>
      </div>
    </div>
  );
}
