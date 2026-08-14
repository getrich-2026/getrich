import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router-dom";
import { z } from "zod";
import {
  createBacktestJob,
  type BacktestBarLoader,
  type BacktestRunRequest,
} from "../../api/backtests";
import { ApiClientError } from "../../api/client";
import { listStrategies } from "../../api/strategies";

const FREQ_OPTIONS = ["1d", "5m", "15m", "30m", "60m", "1h"];

const decimalPattern = /^\d+(?:\.\d+)?$/;

const newBacktestSchema = z
  .object({
    strategy_name: z.string().min(1, "Strategy name is required").max(128),
    symbolsText: z.string().min(1, "At least one symbol is required"),
    startDate: z.string().min(1, "Start date is required"),
    endDate: z.string().min(1, "End date is required"),
    initialCash: z
      .string()
      .min(1, "Initial cash is required")
      .regex(decimalPattern, "Use a positive decimal amount")
      .refine((v) => Number(v) > 0, "Initial cash must be positive"),
    freq: z.string().min(1, "Frequency is required").max(16),
    barLoader: z.enum(["pg", "duckdb"]),
    executionLagBars: z.coerce
      .number()
      .int("Execution lag must be an integer")
      .min(1, "Execution lag must be at least 1"),
    maxAttempts: z.coerce
      .number()
      .int("Max attempts must be an integer")
      .min(1, "Max attempts must be at least 1")
      .max(10, "Max attempts cannot exceed 10"),
    extraFreqsText: z.string().default(""),
    strategyParamsJson: z.string().default("{}"),
    saveArtifacts: z.boolean().default(false),
  })
  .refine((v) => v.endDate >= v.startDate, {
    path: ["endDate"],
    message: "End date must be on or after start date",
  });

type NewBacktestFormValues = z.infer<typeof newBacktestSchema>;

function parseList(text: string): string[] {
  return text
    .split(/[\n,]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

function parseJsonObject(text: string): Record<string, unknown> {
  const trimmed = text.trim();
  if (!trimmed) return {};
  const parsed = JSON.parse(trimmed) as unknown;
  if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("Strategy params must be a JSON object");
  }
  return parsed as Record<string, unknown>;
}

function toShanghaiStart(date: string): string {
  return `${date}T00:00:00+08:00`;
}

function toShanghaiEnd(date: string): string {
  return `${date}T23:59:59+08:00`;
}

const fieldStyle: React.CSSProperties = {
  padding: "8px 12px",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius)",
  fontSize: 14,
  background: "var(--background)",
  color: "var(--foreground)",
};

function FieldError({ message }: { message: string | undefined }) {
  if (!message) return null;
  return <span style={{ color: "var(--danger)", fontSize: 12 }}>{message}</span>;
}

export default function NewBacktestJob() {
  const navigate = useNavigate();
  const idempotencyKeyRef = useRef<string>(crypto.randomUUID());
  const [serverError, setServerError] = useState<string | null>(null);

  const { data: strategies } = useQuery({
    queryKey: ["strategies"],
    queryFn: listStrategies,
  });

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(newBacktestSchema),
    defaultValues: {
      strategy_name: "",
      symbolsText: "000001.SZ",
      startDate: "",
      endDate: "",
      initialCash: "1000000",
      freq: "1d",
      barLoader: "pg" as const,
      executionLagBars: 1,
      maxAttempts: 1,
      extraFreqsText: "",
      strategyParamsJson: "{}",
      saveArtifacts: false,
    },
  });

  const mutation = useMutation({
    mutationFn: (body: BacktestRunRequest) =>
      createBacktestJob(body, idempotencyKeyRef.current),
    onSuccess: (res) => {
      setServerError(null);
      navigate(`/backtests/${encodeURIComponent(res.job_id)}`);
    },
    onError: (err: unknown) => {
      setServerError(
        err instanceof ApiClientError ? err.detail : "Failed to create backtest job",
      );
    },
  });

  const onSubmit = (data: NewBacktestFormValues) => {
    setServerError(null);
    const symbols = parseList(data.symbolsText);
    if (symbols.length === 0) {
      setServerError("At least one symbol is required");
      return;
    }

    let strategyParams: Record<string, unknown>;
    try {
      strategyParams = parseJsonObject(data.strategyParamsJson);
    } catch (err) {
      setServerError(err instanceof Error ? err.message : "Invalid strategy params JSON");
      return;
    }

    const extraFreqs = parseList(data.extraFreqsText);
    const body: BacktestRunRequest = {
      strategy_name: data.strategy_name.trim(),
      symbols,
      start: toShanghaiStart(data.startDate),
      end: toShanghaiEnd(data.endDate),
      initial_cash: data.initialCash,
      freq: data.freq.trim(),
      bar_loader: data.barLoader as BacktestBarLoader,
      max_attempts: data.maxAttempts,
      extra_freqs: extraFreqs,
      execution_lag_bars: data.executionLagBars,
      strategy_params: strategyParams,
      save_artifacts: data.saveArtifacts,
    };
    mutation.mutate(body);
  };

  return (
    <div style={{ maxWidth: 760, margin: "24px auto" }}>
      <div style={{ marginBottom: 16 }}>
        <Link to="/backtests" style={{ fontSize: 13 }}>
          ← Back to Backtests
        </Link>
      </div>

      <h1 className="section-title">New Backtest</h1>
      <p className="text-muted" style={{ marginBottom: 24, fontSize: 13 }}>
        Submit a normal backtest run. Sweep and walk-forward forms are deferred to dedicated pages.
      </p>

      <form
        onSubmit={handleSubmit(onSubmit)}
        className="card"
        style={{ display: "flex", flexDirection: "column", gap: 16 }}
      >
        {serverError && <div className="error-box">{serverError}</div>}

        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label htmlFor="strategy_name" style={{ fontWeight: 500, fontSize: 13 }}>
            Strategy Name *
          </label>
          <input
            id="strategy_name"
            list="strategy-name-options"
            style={fieldStyle}
            placeholder="MACross"
            {...register("strategy_name")}
          />
          <datalist id="strategy-name-options">
            {(strategies ?? []).map((s) => (
              <option key={s.id} value={s.code || s.name}>
                {s.name}
              </option>
            ))}
          </datalist>
          <FieldError message={errors.strategy_name?.message} />
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label htmlFor="symbolsText" style={{ fontWeight: 500, fontSize: 13 }}>
            Symbols *
          </label>
          <textarea
            id="symbolsText"
            rows={3}
            style={{ ...fieldStyle, resize: "vertical" }}
            placeholder="000001.SZ, 000002.SZ"
            {...register("symbolsText")}
          />
          <span className="text-muted" style={{ fontSize: 12 }}>
            Separate symbols by comma or newline.
          </span>
          <FieldError message={errors.symbolsText?.message} />
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label htmlFor="startDate" style={{ fontWeight: 500, fontSize: 13 }}>
              Start Date *
            </label>
            <input id="startDate" type="date" style={fieldStyle} {...register("startDate")} />
            <FieldError message={errors.startDate?.message} />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label htmlFor="endDate" style={{ fontWeight: 500, fontSize: 13 }}>
              End Date *
            </label>
            <input id="endDate" type="date" style={fieldStyle} {...register("endDate")} />
            <FieldError message={errors.endDate?.message} />
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 16 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label htmlFor="initialCash" style={{ fontWeight: 500, fontSize: 13 }}>
              Initial Cash *
            </label>
            <input id="initialCash" inputMode="decimal" style={fieldStyle} {...register("initialCash")} />
            <FieldError message={errors.initialCash?.message} />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label htmlFor="freq" style={{ fontWeight: 500, fontSize: 13 }}>
              Frequency *
            </label>
            <select id="freq" style={fieldStyle} {...register("freq")}>
              {FREQ_OPTIONS.map((freq) => (
                <option key={freq} value={freq}>
                  {freq}
                </option>
              ))}
            </select>
            <FieldError message={errors.freq?.message} />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label htmlFor="barLoader" style={{ fontWeight: 500, fontSize: 13 }}>
              Bar Loader
            </label>
            <select id="barLoader" style={fieldStyle} {...register("barLoader")}>
              <option value="pg">PostgreSQL</option>
              <option value="duckdb">DuckDB</option>
            </select>
            <FieldError message={errors.barLoader?.message} />
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label htmlFor="executionLagBars" style={{ fontWeight: 500, fontSize: 13 }}>
              Execution Lag Bars
            </label>
            <input
              id="executionLagBars"
              type="number"
              min={1}
              style={fieldStyle}
              {...register("executionLagBars")}
            />
            <FieldError message={errors.executionLagBars?.message} />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label htmlFor="maxAttempts" style={{ fontWeight: 500, fontSize: 13 }}>
              Max Attempts
            </label>
            <input
              id="maxAttempts"
              type="number"
              min={1}
              max={10}
              style={fieldStyle}
              {...register("maxAttempts")}
            />
            <FieldError message={errors.maxAttempts?.message} />
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label htmlFor="extraFreqsText" style={{ fontWeight: 500, fontSize: 13 }}>
            Extra Frequencies
          </label>
          <input
            id="extraFreqsText"
            style={fieldStyle}
            placeholder="5m, 1h"
            {...register("extraFreqsText")}
          />
          <span className="text-muted" style={{ fontSize: 12 }}>
            Optional comma-separated frequencies for multi-period contexts.
          </span>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label htmlFor="strategyParamsJson" style={{ fontWeight: 500, fontSize: 13 }}>
            Strategy Params JSON
          </label>
          <textarea
            id="strategyParamsJson"
            rows={5}
            style={{ ...fieldStyle, fontFamily: "var(--font-mono, monospace)", resize: "vertical" }}
            {...register("strategyParamsJson")}
          />
          <span className="text-muted" style={{ fontSize: 12 }}>
            Must be a JSON object, for example {`{"fast": 5, "slow": 20}`}.
          </span>
        </div>

        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
          <input type="checkbox" {...register("saveArtifacts")} />
          Save report artifacts
        </label>

        <div style={{ display: "flex", gap: 12, justifyContent: "flex-end" }}>
          <Link
            to="/backtests"
            style={{
              padding: "8px 14px",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              color: "var(--foreground)",
              textDecoration: "none",
              fontSize: 13,
            }}
          >
            Cancel
          </Link>
          <button
            type="submit"
            disabled={isSubmitting || mutation.isPending}
            style={{
              padding: "8px 14px",
              border: "1px solid var(--primary)",
              borderRadius: "var(--radius)",
              background: "var(--primary)",
              color: "var(--primary-foreground)",
              cursor: isSubmitting || mutation.isPending ? "not-allowed" : "pointer",
              fontSize: 13,
              fontWeight: 600,
            }}
          >
            {mutation.isPending ? "Creating…" : "Create Backtest"}
          </button>
        </div>
      </form>
    </div>
  );
}
