import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useState, useEffect } from "react";
import {
  getSignalDetail,
  markSignalRead,
  executeSignal,
  type SignalDetail,
  type ExecuteSignalRequest,
} from "../api/signals";
import { ApiClientError } from "../api/client";

// ---------------------------------------------------------------------------
// Execute form schema
// ---------------------------------------------------------------------------

const executeSchema = z.object({
  executed_price: z.coerce.number().min(0, "Price must be ≥ 0"),
  executed_quantity: z.coerce
    .number()
    .int("Quantity must be a whole number")
    .min(1, "Quantity must be ≥ 1"),
  executed_at: z.string().optional(),
  note: z.string().max(500).optional(),
});

type ExecuteFormValues = z.infer<typeof executeSchema>;

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function fmtNum(n: number, decimals = 2): string {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function fmtPct(n: number): string {
  return `${(n * 100).toFixed(2)}%`;
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

function badgeColor(
  value: string,
): { bg: string; fg: string } {
  switch (value) {
    case "critical":
      return { bg: "var(--danger)", fg: "#fff" };
    case "high":
      return { bg: "#f97316", fg: "#fff" };
    case "normal":
      return { bg: "var(--primary)", fg: "var(--primary-foreground)" };
    case "low":
      return { bg: "var(--muted)", fg: "var(--muted-foreground)" };
    case "buy":
    case "entry":
    case "long":
    case "active":
      return { bg: "var(--success, #22c55e)", fg: "#fff" };
    case "sell":
    case "exit":
    case "short":
      return { bg: "var(--danger)", fg: "#fff" };
    case "expired":
    case "cancelled":
      return { bg: "var(--muted)", fg: "var(--muted-foreground)" };
    default:
      return { bg: "var(--muted)", fg: "var(--muted-foreground)" };
  }
}

// ---------------------------------------------------------------------------
// Metric row component
// ---------------------------------------------------------------------------

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
        padding: "6px 0",
        borderBottom: "1px solid var(--border)",
        fontSize: 13,
      }}
    >
      <span className="text-muted">{label}</span>
      <span
        style={{ fontFamily: mono ? "var(--font-mono, monospace)" : undefined }}
      >
        {value}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function SignalDetailPage() {
  const { code } = useParams<{ code: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [executeError, setExecuteError] = useState<string | null>(null);
  const [executeSuccess, setExecuteSuccess] = useState(false);

  // Fetch signal detail
  const {
    data: res,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["signal-detail", code],
    queryFn: () => getSignalDetail(code!),
    enabled: !!code,
  });

  const signal: SignalDetail | undefined = res?.data;

  // Auto-mark as read when detail loads and signal is not yet read
  const readMutation = useMutation({
    mutationFn: () => markSignalRead(code!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["signal-detail", code] });
    },
  });

  useEffect(() => {
    if (signal && signal.user_state && !signal.user_state.is_read) {
      readMutation.mutate();
    }
    // Only run when signal first loads — intentionally not tracking readMutation
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signal?.id]);

  // Execute form — no explicit type param to avoid zod v4 + hookform resolver type mismatch
  const executeForm = useForm({
    resolver: zodResolver(executeSchema),
    defaultValues: {
      executed_price: signal?.trigger_price ?? 0,
      executed_quantity: signal?.suggested_quantity || 1,
    },
  });
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = executeForm;

  // Keep form values in sync with signal data
  useEffect(() => {
    executeForm.reset({
      executed_price: signal?.trigger_price ?? 0,
      executed_quantity: signal?.suggested_quantity || 1,
    });
  }, [signal?.trigger_price, signal?.suggested_quantity, executeForm]);

  const executeMutation = useMutation({
    mutationFn: (body: ExecuteSignalRequest) => executeSignal(code!, body),
    onSuccess: () => {
      setExecuteSuccess(true);
      setExecuteError(null);
      queryClient.invalidateQueries({ queryKey: ["signal-detail", code] });
    },
    onError: (err: unknown) => {
      setExecuteError(
        err instanceof ApiClientError ? err.detail : "Execution failed",
      );
    },
  });

  const onExecute = (data: ExecuteFormValues) => {
    setExecuteError(null);
    setExecuteSuccess(false);
    executeMutation.mutate({
      executed_price: data.executed_price,
      executed_quantity: data.executed_quantity,
      executed_at: data.executed_at || undefined,
      note: data.note || undefined,
    });
  };

  // ---- render ----

  if (isLoading) {
    return (
      <div style={{ maxWidth: 760, margin: "24px auto" }}>
        <div className="loading">Loading signal…</div>
      </div>
    );
  }

  if (error || !signal) {
    return (
      <div style={{ maxWidth: 760, margin: "24px auto" }}>
        <div className="error-box">
          {error instanceof Error ? error.message : "Signal not found"}
        </div>
        <button
          onClick={() => navigate(-1)}
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
          ← Back
        </button>
      </div>
    );
  }

  const isAlreadyExecuted = signal.user_state?.is_executed ?? false;
  const isExpired = signal.status === "expired" || signal.status === "cancelled";
  const canExecute = !isAlreadyExecuted && !isExpired;

  return (
    <div style={{ maxWidth: 760, margin: "24px auto" }}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 20,
        }}
      >
        <div>
          <button
            onClick={() => navigate(-1)}
            style={{
              padding: "4px 12px",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              background: "var(--card-bg)",
              cursor: "pointer",
              fontSize: 13,
              marginBottom: 8,
            }}
          >
            ← Back to Signals
          </button>
          <h1 className="section-title" style={{ margin: 0 }}>
            Signal {signal.id}
          </h1>
        </div>
        <span
          style={{
            padding: "4px 12px",
            borderRadius: 999,
            fontSize: 12,
            fontWeight: 600,
            backgroundColor: badgeColor(signal.status).bg,
            color: badgeColor(signal.status).fg,
          }}
        >
          {signal.status.toUpperCase()}
        </span>
      </div>

      {/* ---- Strategy + Core Info ---- */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>
          Strategy &amp; Core Info
        </h2>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 0 }}>
          <MetricRow label="Strategy" value={signal.strategy.name} />
          <MetricRow label="Symbol" value={`${signal.symbol_name} (${signal.symbol})`} />
          <MetricRow label="Signal Type" value={signal.signal_type} />
          <MetricRow label="Action" value={signal.action} />
          <MetricRow label="Direction" value={signal.direction} />
          <MetricRow label="Exchange" value={signal.exchange} />
          <MetricRow label="Trigger Time" value={fmtDate(signal.trigger_time)} />
          <MetricRow label="Expires" value={fmtDate(signal.expired_at)} />
        </div>
      </div>

      {/* ---- Price Targets ---- */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>
          Price Targets &amp; Confidence
        </h2>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 0 }}>
          <MetricRow label="Trigger Price" value={fmtNum(signal.trigger_price, 4)} mono />
          <MetricRow label="Target Price" value={fmtNum(signal.target_price, 4)} mono />
          <MetricRow
            label="Stop Loss"
            value={signal.stop_loss_price > 0 ? fmtNum(signal.stop_loss_price, 4) : "—"}
            mono
          />
          <MetricRow label="Confidence" value={fmtPct(signal.confidence)} />
          <MetricRow label="Urgency" value={signal.urgency} />
          <MetricRow label="Position %" value={fmtPct(signal.position_pct)} />
        </div>
      </div>

      {/* ---- Reason ---- */}
      {(signal.reason || signal.reason_detail) && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>
            Reason
          </h2>
          {signal.reason && (
            <p style={{ fontSize: 13, whiteSpace: "pre-wrap", marginBottom: 12 }}>
              {signal.reason}
            </p>
          )}
          {signal.reason_detail && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 0 }}>
              <MetricRow
                label="Spread Current"
                value={fmtNum(signal.reason_detail.spread_current, 4)}
                mono
              />
              <MetricRow
                label="Spread Mean"
                value={fmtNum(signal.reason_detail.spread_mean, 4)}
                mono
              />
              <MetricRow
                label="Z-Score"
                value={fmtNum(signal.reason_detail.z_score, 2)}
                mono
              />
              <MetricRow label="Trigger Rule" value={signal.reason_detail.trigger_rule} />
            </div>
          )}
        </div>
      )}

      {/* ---- Market Snapshot ---- */}
      {signal.market_snapshot && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>
            Market Snapshot — {fmtDate(signal.market_snapshot.snapshot_time)}
          </h2>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 0 }}>
            <MetricRow label="Open" value={fmtNum(signal.market_snapshot.open, 4)} mono />
            <MetricRow label="High" value={fmtNum(signal.market_snapshot.high, 4)} mono />
            <MetricRow label="Low" value={fmtNum(signal.market_snapshot.low, 4)} mono />
            <MetricRow label="Close" value={fmtNum(signal.market_snapshot.close, 4)} mono />
            <MetricRow label="Volume" value={signal.market_snapshot.volume.toLocaleString()} />
            <MetricRow
              label="Open Interest"
              value={signal.market_snapshot.open_interest.toLocaleString()}
            />
          </div>
          <h3
            style={{
              fontSize: 13,
              fontWeight: 600,
              marginTop: 12,
              marginBottom: 8,
              color: "var(--muted-foreground)",
            }}
          >
            Indicators
          </h3>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 0 }}>
            <MetricRow label="MA(5)" value={fmtNum(signal.market_snapshot.indicators.ma5, 4)} mono />
            <MetricRow label="MA(20)" value={fmtNum(signal.market_snapshot.indicators.ma20, 4)} mono />
            <MetricRow label="RSI(14)" value={fmtNum(signal.market_snapshot.indicators.rsi_14, 1)} />
            <MetricRow label="ATR(14)" value={fmtNum(signal.market_snapshot.indicators.atr_14, 4)} mono />
          </div>
        </div>
      )}

      {/* ---- Historical Performance ---- */}
      {signal.historical_performance &&
        signal.historical_performance.similar_signals_count > 0 && (
          <div className="card" style={{ marginBottom: 16 }}>
            <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>
              Historical Performance (Similar Signals)
            </h2>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 0 }}>
              <MetricRow
                label="Similar Signals"
                value={String(signal.historical_performance.similar_signals_count)}
              />
              <MetricRow
                label="Win Rate"
                value={fmtPct(signal.historical_performance.win_rate)}
              />
              <MetricRow
                label="Avg Return"
                value={fmtPct(signal.historical_performance.avg_return)}
              />
              <MetricRow
                label="Avg Holding Days"
                value={fmtNum(signal.historical_performance.avg_holding_days, 1)}
              />
            </div>
          </div>
        )}

      {/* ---- User State ---- */}
      {signal.user_state && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>
            Your Status
          </h2>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 0 }}>
            <MetricRow
              label="Read"
              value={signal.user_state.is_read ? `✓ ${fmtDate(signal.user_state.read_at)}` : "✗ Unread"}
            />
            <MetricRow
              label="Executed"
              value={
                signal.user_state.is_executed
                  ? `✓ @ ${fmtNum(signal.user_state.executed_price ?? 0, 4)}`
                  : "Not executed"
              }
            />
          </div>
          {signal.user_state.note && (
            <div style={{ marginTop: 8, fontSize: 13 }}>
              <span className="text-muted">Note: </span>
              {signal.user_state.note}
            </div>
          )}
        </div>
      )}

      {/* ---- Execute Form ---- */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>
          Record Execution
        </h2>

        {!canExecute && (
          <div
            style={{
              padding: "8px 12px",
              borderRadius: "var(--radius)",
              background: "var(--muted)",
              color: "var(--muted-foreground)",
              fontSize: 13,
              marginBottom: 12,
            }}
          >
            {isAlreadyExecuted
              ? "This signal has already been executed."
              : "This signal is expired or cancelled and cannot be executed."}
          </div>
        )}

        {executeSuccess && (
          <div
            style={{
              padding: "8px 12px",
              borderRadius: "var(--radius)",
              background: "var(--success, #22c55e)",
              color: "#fff",
              fontSize: 13,
              marginBottom: 12,
            }}
          >
            ✓ Execution recorded successfully.
          </div>
        )}

        {executeError && (
          <div
            style={{
              padding: "8px 12px",
              borderRadius: "var(--radius)",
              background: "var(--danger)",
              color: "var(--danger-foreground, #fff)",
              fontSize: 13,
              marginBottom: 12,
            }}
          >
            {executeError}
          </div>
        )}

        <form
          onSubmit={handleSubmit(onExecute)}
          style={{ display: "flex", flexDirection: "column", gap: 12 }}
        >
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            {/* Executed Price */}
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <label htmlFor="executed_price" style={{ fontWeight: 500, fontSize: 13 }}>
                Executed Price
              </label>
              <input
                id="executed_price"
                type="number"
                step="any"
                disabled={!canExecute}
                {...register("executed_price")}
                style={{
                  padding: "8px 12px",
                  border: `1px solid ${errors.executed_price ? "var(--danger)" : "var(--border)"}`,
                  borderRadius: "var(--radius)",
                  fontSize: 14,
                  background: "var(--background)",
                  color: "var(--foreground)",
                }}
              />
              {errors.executed_price && (
                <span style={{ color: "var(--danger)", fontSize: 12 }}>
                  {errors.executed_price.message}
                </span>
              )}
            </div>

            {/* Executed Quantity */}
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <label htmlFor="executed_quantity" style={{ fontWeight: 500, fontSize: 13 }}>
                Quantity
              </label>
              <input
                id="executed_quantity"
                type="number"
                step="1"
                disabled={!canExecute}
                {...register("executed_quantity")}
                style={{
                  padding: "8px 12px",
                  border: `1px solid ${errors.executed_quantity ? "var(--danger)" : "var(--border)"}`,
                  borderRadius: "var(--radius)",
                  fontSize: 14,
                  background: "var(--background)",
                  color: "var(--foreground)",
                }}
              />
              {errors.executed_quantity && (
                <span style={{ color: "var(--danger)", fontSize: 12 }}>
                  {errors.executed_quantity.message}
                </span>
              )}
            </div>
          </div>

          {/* Note */}
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label htmlFor="note" style={{ fontWeight: 500, fontSize: 13 }}>
              Note <span className="text-muted">(optional)</span>
            </label>
            <input
              id="note"
              type="text"
              maxLength={500}
              disabled={!canExecute}
              placeholder="Execution notes, reasons for deviation…"
              {...register("note")}
              style={{
                padding: "8px 12px",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius)",
                fontSize: 14,
                background: "var(--background)",
                color: "var(--foreground)",
              }}
            />
          </div>

          <button
            type="submit"
            disabled={!canExecute || isSubmitting}
            style={{
              padding: "10px 16px",
              marginTop: 4,
              border: "none",
              borderRadius: "var(--radius)",
              background: canExecute ? "var(--primary)" : "var(--muted)",
              color: canExecute ? "var(--primary-foreground)" : "var(--muted-foreground)",
              fontSize: 14,
              fontWeight: 600,
              cursor: canExecute && !isSubmitting ? "pointer" : "not-allowed",
              opacity: isSubmitting ? 0.7 : 1,
            }}
          >
            {isSubmitting
              ? "Recording…"
              : isAlreadyExecuted
                ? "Already Executed"
                : "Record Execution"}
          </button>
        </form>
      </div>
    </div>
  );
}
