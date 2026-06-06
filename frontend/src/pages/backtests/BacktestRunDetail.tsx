import { useQuery } from "@tanstack/react-query";
import { useState, type CSSProperties } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import type { DrawdownPoint, EquityPoint } from "../../api/strategies";
import {
  downloadBacktestRunArtifact,
  getBacktestRun,
  getBacktestRunArtifacts,
  getBacktestRunEquityCurve,
  getBacktestRunMetrics,
  getBacktestRunPositions,
  type BacktestArtifact,
  type BacktestEquityPoint,
  type BacktestMetrics,
  type BacktestPosition,
  type BacktestRunStatus,
} from "../../api/backtestRuns";
import EquityCurveChart from "../../components/EquityCurveChart";

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

function fmtMoney(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function fmtNum(value: number | null | undefined, digits = 4): string {
  if (value === null || value === undefined) return "—";
  return value.toFixed(digits);
}

function fmtInt(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return String(value);
}

function fmtPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(2)}%`;
}

function statusBadge(status: BacktestRunStatus) {
  const map: Record<BacktestRunStatus, { bg: string; fg: string }> = {
    running: { bg: "var(--primary)", fg: "var(--primary-foreground)" },
    completed: { bg: "var(--success)", fg: "#fff" },
    failed: { bg: "var(--danger)", fg: "#fff" },
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

function MetricCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="card card-stat">
      <div className="lbl">{label}</div>
      <div className="val" style={{ color }}>
        {value}
      </div>
    </div>
  );
}

function compactJson(value: Record<string, unknown>): string {
  return JSON.stringify(value);
}

function formatJson(value: Record<string, unknown>): string {
  return JSON.stringify(value, null, 2);
}

function isSafeHttpUri(uri: string): boolean {
  return uri.startsWith("https://") || uri.startsWith("http://");
}

function toEquityChartData(points: BacktestEquityPoint[]): EquityPoint[] {
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

function toDrawdownData(points: BacktestEquityPoint[]): DrawdownPoint[] {
  let highWaterMark = Number.NEGATIVE_INFINITY;
  return points.map((point) => {
    highWaterMark = Math.max(highWaterMark, point.equity);
    const drawdown = highWaterMark > 0 ? point.equity / highWaterMark - 1 : 0;
    return { date: point.dt, drawdown };
  });
}

function SectionError({ error }: { error: unknown }) {
  return (
    <div className="error-box">
      {error instanceof Error ? error.message : "Failed to load section"}
    </div>
  );
}

function MetricsCard({
  metrics,
  isLoading,
  error,
}: {
  metrics: BacktestMetrics | undefined;
  isLoading: boolean;
  error: unknown;
}) {
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h2 style={{ fontSize: 16, marginBottom: 12 }}>Performance Metrics</h2>
      {isLoading && <div className="loading">Loading metrics…</div>}
      {error ? <SectionError error={error} /> : null}
      {metrics && (
        <div className="card-grid">
          <MetricCard label="Total Return" value={fmtPct(metrics.total_return)} />
          <MetricCard label="Log Return" value={fmtPct(metrics.log_return)} />
          <MetricCard label="Annualized Return" value={fmtPct(metrics.annualized_return)} />
          <MetricCard
            label="Annualized Volatility"
            value={fmtPct(metrics.annualized_volatility)}
          />
          <MetricCard label="Sharpe Ratio" value={fmtNum(metrics.sharpe_ratio)} />
          <MetricCard label="Sortino Ratio" value={fmtNum(metrics.sortino_ratio)} />
          <MetricCard label="Calmar Ratio" value={fmtNum(metrics.calmar_ratio)} />
          <MetricCard
            label="Max Drawdown"
            value={fmtPct(metrics.max_drawdown)}
            color="var(--danger)"
          />
          <MetricCard
            label="Max DD Duration"
            value={fmtInt(metrics.max_drawdown_duration)}
          />
          <MetricCard label="Total Trades" value={fmtInt(metrics.total_trades)} />
          <MetricCard label="N Bars" value={fmtInt(metrics.n_bars)} />
          <MetricCard label="Total Fees" value={fmtMoney(metrics.total_fees)} />
          <MetricCard label="Total Turnover" value={fmtMoney(metrics.total_turnover)} />
          <MetricCard label="Turnover Rate" value={fmtPct(metrics.turnover_rate)} />
          <MetricCard label="Risk-Free Rate" value={fmtPct(metrics.risk_free_rate)} />
          <MetricCard
            label="Trading Days / Year"
            value={fmtInt(metrics.trading_days_per_year)}
          />
        </div>
      )}
      {!isLoading && !error && !metrics && (
        <div className="text-muted" style={{ textAlign: "center", padding: 24 }}>
          No metrics recorded for this run.
        </div>
      )}
    </div>
  );
}

function EquityCurveCard({
  points,
  isLoading,
  error,
}: {
  points: BacktestEquityPoint[] | undefined;
  isLoading: boolean;
  error: unknown;
}) {
  const chartData = points ? toEquityChartData(points) : [];
  const drawdownData = points ? toDrawdownData(points) : [];
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h2 style={{ fontSize: 16, marginBottom: 12 }}>Equity Curve</h2>
      {isLoading && <div className="loading">Loading equity curve…</div>}
      {error ? <SectionError error={error} /> : null}
      {!isLoading && !error && chartData.length > 0 && (
        <EquityCurveChart equity={chartData} drawdown={drawdownData} />
      )}
      {!isLoading && !error && chartData.length === 0 && (
        <div className="text-muted" style={{ textAlign: "center", padding: 48 }}>
          No equity data available for this run.
        </div>
      )}
    </div>
  );
}

function PositionsTable({ positions }: { positions: BacktestPosition[] }) {
  if (positions.length === 0) {
    return (
      <div className="text-muted" style={{ textAlign: "center", padding: 24 }}>
        No final positions recorded.
      </div>
    );
  }
  return (
    <div style={{ overflowX: "auto" }}>
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Qty</th>
            <th>Position JSON</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((position) => (
            <tr key={position.symbol}>
              <td style={{ fontFamily: "monospace", fontSize: 12 }}>{position.symbol}</td>
              <td>{fmtNum(position.qty, 4)}</td>
              <td
                style={{
                  fontFamily: "monospace",
                  fontSize: 12,
                  maxWidth: 520,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
                title={compactJson(position.position_json)}
              >
                {compactJson(position.position_json)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PositionsCard({
  positions,
  isLoading,
  error,
}: {
  positions: BacktestPosition[] | undefined;
  isLoading: boolean;
  error: unknown;
}) {
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h2 style={{ fontSize: 16, marginBottom: 12 }}>Final Positions</h2>
      {isLoading && <div className="loading">Loading positions…</div>}
      {error ? <SectionError error={error} /> : null}
      {!isLoading && !error && <PositionsTable positions={positions ?? []} />}
    </div>
  );
}

function ArtifactUri({
  uri,
  runId,
  artifactId,
}: {
  uri: string;
  runId: string;
  artifactId: string;
}) {
  // External HTTPS URIs keep their external-link treatment (the artifact
  // row was created out-of-band; we do not proxy or sign them).
  if (isSafeHttpUri(uri)) {
    return (
      <a href={uri} target="_blank" rel="noreferrer" style={{ fontSize: 12 }}>
        {uri}
      </a>
    );
  }

  // Local / file URI artifacts are streamed through the authenticated
  // /content endpoint so the user can download them.
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <span
        style={{
          fontFamily: "monospace",
          fontSize: 12,
          wordBreak: "break-all",
        }}
      >
        {uri}
      </span>
      <ArtifactDownloadButton
        runId={runId}
        artifactId={artifactId}
        uri={uri}
      />
    </div>
  );
}

function ArtifactDownloadButton({
  runId,
  artifactId,
  uri,
}: {
  runId: string;
  artifactId: string;
  uri: string;
}) {
  const [state, setState] = useState<"idle" | "downloading" | "error">(
    "idle",
  );
  const [error, setError] = useState<string | null>(null);

  async function handleClick() {
    setState("downloading");
    setError(null);
    try {
      await downloadBacktestRunArtifact(runId, artifactId, baseName(uri));
      setState("idle");
    } catch (err) {
      setState("error");
      setError(err instanceof Error ? err.message : "download failed");
    }
  }

  return (
    <span style={{ display: "inline-flex", flexDirection: "column" }}>
      <button
        type="button"
        onClick={handleClick}
        disabled={state === "downloading"}
        title={error ?? undefined}
        style={{
          padding: "2px 10px",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius)",
          background: "var(--card-bg)",
          cursor: state === "downloading" ? "wait" : "pointer",
          fontSize: 12,
          whiteSpace: "nowrap",
        }}
      >
        {state === "downloading" ? "Downloading…" : "Download"}
      </button>
      {state === "error" && error ? (
        <span style={{ color: "var(--danger, #c00)", fontSize: 11 }}>
          {error}
        </span>
      ) : null}
    </span>
  );
}

function baseName(uri: string): string {
  const cleaned = uri.split("?")[0] ?? uri;
  const last = cleaned.split("/").pop() ?? cleaned;
  // Strip Windows drive letter if present ("C:" -> "" after split).
  return last || "artifact";
}

function ArtifactsTable({ artifacts }: { artifacts: BacktestArtifact[] }) {
  if (artifacts.length === 0) {
    return (
      <div className="text-muted" style={{ textAlign: "center", padding: 24 }}>
        No artifacts saved for this run.
      </div>
    );
  }
  return (
    <div style={{ overflowX: "auto" }}>
      <table>
        <thead>
          <tr>
            <th>Type</th>
            <th>URI</th>
            <th>Checksum</th>
            <th>Created</th>
            <th>Meta</th>
          </tr>
        </thead>
        <tbody>
          {artifacts.map((artifact) => (
            <tr key={artifact.id}>
              <td>{artifact.artifact_type}</td>
              <td style={{ maxWidth: 360, wordBreak: "break-all" }}>
                <ArtifactUri
                  uri={artifact.uri}
                  runId={artifact.run_id}
                  artifactId={artifact.id}
                />
              </td>
              <td style={{ fontFamily: "monospace", fontSize: 12 }}>
                {artifact.checksum ?? "—"}
              </td>
              <td style={{ fontSize: 12 }}>{fmtDate(artifact.created_at)}</td>
              <td
                style={{
                  fontFamily: "monospace",
                  fontSize: 12,
                  maxWidth: 300,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
                title={compactJson(artifact.meta)}
              >
                {compactJson(artifact.meta)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ArtifactsCard({
  artifacts,
  isLoading,
  error,
}: {
  artifacts: BacktestArtifact[] | undefined;
  isLoading: boolean;
  error: unknown;
}) {
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h2 style={{ fontSize: 16, marginBottom: 12 }}>Artifacts</h2>
      {isLoading && <div className="loading">Loading artifacts…</div>}
      {error ? <SectionError error={error} /> : null}
      {!isLoading && !error && <ArtifactsTable artifacts={artifacts ?? []} />}
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

export default function BacktestRunDetail() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();

  const {
    data: run,
    isLoading: runLoading,
    error: runError,
  } = useQuery({
    queryKey: ["backtest-run", runId],
    queryFn: () => getBacktestRun(runId!),
    enabled: !!runId,
  });

  const metricsQuery = useQuery({
    queryKey: ["backtest-run-metrics", runId],
    queryFn: () => getBacktestRunMetrics(runId!),
    enabled: !!runId,
  });

  const equityQuery = useQuery({
    queryKey: ["backtest-run-equity", runId],
    queryFn: () => getBacktestRunEquityCurve(runId!),
    enabled: !!runId,
  });

  const positionsQuery = useQuery({
    queryKey: ["backtest-run-positions", runId],
    queryFn: () => getBacktestRunPositions(runId!),
    enabled: !!runId,
  });

  const artifactsQuery = useQuery({
    queryKey: ["backtest-run-artifacts", runId],
    queryFn: () => getBacktestRunArtifacts(runId!),
    enabled: !!runId,
  });

  if (runLoading) {
    return (
      <div style={{ maxWidth: 980, margin: "24px auto" }}>
        <div className="loading">Loading backtest run result…</div>
      </div>
    );
  }

  if (runError || !run) {
    return (
      <div style={{ maxWidth: 980, margin: "24px auto" }}>
        <div className="error-box">
          {runError instanceof Error ? runError.message : "Backtest run not found"}
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
              Backtest Run Result
            </h1>
            <div style={{ fontFamily: "monospace", fontSize: 13 }}>{run.run_id}</div>
          </div>
          {statusBadge(run.status)}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 24 }}>
          <div>
            <MetricRow label="Strategy" value={run.strategy_name || "—"} />
            <MetricRow label="Strategy ID" value={run.strategy_id || "—"} mono />
            <MetricRow label="Strategy Names" value={run.strategy_names.join(", ") || "—"} />
            <MetricRow label="Symbols" value={run.symbols.join(", ") || "—"} />
            <MetricRow label="Frequency" value={run.freq || "—"} />
            <MetricRow label="Period" value={`${fmtDate(run.start_at)} — ${fmtDate(run.end_at)}`} />
          </div>
          <div>
            <MetricRow label="Initial Cash" value={fmtMoney(run.initial_cash)} />
            <MetricRow label="Final Cash" value={fmtMoney(run.final_cash)} />
            <MetricRow label="Final Equity" value={fmtMoney(run.final_equity)} />
            <MetricRow
              label="Benchmark Final Equity"
              value={fmtMoney(run.benchmark_final_equity)}
            />
            <MetricRow label="Config Fingerprint" value={run.config_fingerprint || "—"} mono />
            <MetricRow label="Created" value={fmtDate(run.created_at)} />
            <MetricRow label="Completed" value={fmtDate(run.completed_at)} />
          </div>
        </div>
      </div>

      {run.error_message && (
        <div className="error-box" style={{ marginTop: 16 }}>
          {run.error_message}
        </div>
      )}

      <MetricsCard
        metrics={metricsQuery.data}
        isLoading={metricsQuery.isLoading}
        error={metricsQuery.error}
      />
      <EquityCurveCard
        points={equityQuery.data?.points}
        isLoading={equityQuery.isLoading}
        error={equityQuery.error}
      />
      <PositionsCard
        positions={positionsQuery.data?.list}
        isLoading={positionsQuery.isLoading}
        error={positionsQuery.error}
      />
      <ArtifactsCard
        artifacts={artifactsQuery.data?.list}
        isLoading={artifactsQuery.isLoading}
        error={artifactsQuery.error}
      />

      <div className="card" style={{ marginTop: 16 }}>
        <h2 style={{ fontSize: 16, marginBottom: 12 }}>Config JSON</h2>
        <pre style={preStyle}>{formatJson(run.config)}</pre>
      </div>
    </div>
  );
}
