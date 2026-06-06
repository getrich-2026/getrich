import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import type { CSSProperties } from "react";
import { useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router-dom";
import { z } from "zod";
import {
  createSweepJob,
  type BacktestBarLoader,
  type BacktestSearchSpec,
  type SweepRunRequest,
} from "../../api/backtests";
import { ApiClientError } from "../../api/client";
import { listStrategies } from "../../api/strategies";

const FREQ_OPTIONS = ["1d", "5m", "15m", "30m", "60m", "1h"];
const METRIC_OPTIONS = [
  "sharpe_ratio",
  "sortino_ratio",
  "calmar_ratio",
  "total_return",
  "annualized_return",
  "max_drawdown",
];

const decimalPattern = /^\d+(?:\.\d+)?$/;

const newSweepSchema = z
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
    maxAttempts: z.coerce
      .number()
      .int("Max attempts must be an integer")
      .min(1, "Max attempts must be at least 1")
      .max(10, "Max attempts cannot exceed 10"),
    sweepId: z.string().max(128, "Sweep ID cannot exceed 128 chars").default(""),
    searchSpecJson: z.string().min(1, "Search spec JSON is required"),
    selectMetric: z.string().min(1, "Select metric is required").max(64),
    maximize: z.boolean().default(true),
    failFast: z.boolean().default(false),
    strategyParamsJson: z.string().default("{}"),
  })
  .refine((v) => v.endDate >= v.startDate, {
    path: ["endDate"],
    message: "End date must be on or after start date",
  });

type NewSweepFormValues = z.infer<typeof newSweepSchema>;

function parseList(text: string): string[] {
  return text
    .split(/[\n,]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

function parseJsonObject(text: string, label: string): Record<string, unknown> {
  const trimmed = text.trim();
  if (!trimmed) return {};
  const parsed = JSON.parse(trimmed) as unknown;
  if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error(`${label} must be a JSON object`);
  }
  return parsed as Record<string, unknown>;
}

function parseSearchSpec(text: string): BacktestSearchSpec {
  const spec = parseJsonObject(text, "Search spec");
  const space = spec.space;
  if (space === null || Array.isArray(space) || typeof space !== "object") {
    throw new Error("Search spec must include a JSON object field named space");
  }
  if (Object.keys(space).length === 0) {
    throw new Error("Search spec space must contain at least one parameter");
  }
  const constraints = spec.constraints;
  if (constraints !== undefined && !Array.isArray(constraints)) {
    throw new Error("Search spec constraints must be an array when provided");
  }
  return {
    space: space as Record<string, unknown>,
    constraints: constraints ?? [],
  };
}

function toShanghaiStart(date: string): string {
  return `${date}T00:00:00+08:00`;
}

function toShanghaiEnd(date: string): string {
  return `${date}T23:59:59+08:00`;
}

const fieldStyle: CSSProperties = {
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

export default function NewSweepJob() {
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
    resolver: zodResolver(newSweepSchema),
    defaultValues: {
      strategy_name: "",
      symbolsText: "000001.SZ",
      startDate: "",
      endDate: "",
      initialCash: "1000000",
      freq: "1d",
      barLoader: "pg" as const,
      maxAttempts: 1,
      sweepId: "",
      searchSpecJson: JSON.stringify(
        {
          space: {
            fast: [5, 10],
            slow: [20, 60],
          },
          constraints: [],
        },
        null,
        2,
      ),
      selectMetric: "sharpe_ratio",
      maximize: true,
      failFast: false,
      strategyParamsJson: "{}",
    },
  });

  const mutation = useMutation({
    mutationFn: (body: SweepRunRequest) => createSweepJob(body, idempotencyKeyRef.current),
    onSuccess: (res) => {
      setServerError(null);
      navigate(`/backtests/${encodeURIComponent(res.job_id)}`);
    },
    onError: (err: unknown) => {
      setServerError(err instanceof ApiClientError ? err.detail : "Failed to create sweep job");
    },
  });

  const onSubmit = (data: NewSweepFormValues) => {
    setServerError(null);
    const symbols = parseList(data.symbolsText);
    if (symbols.length === 0) {
      setServerError("At least one symbol is required");
      return;
    }

    let searchSpec: BacktestSearchSpec;
    let strategyParams: Record<string, unknown>;
    try {
      searchSpec = parseSearchSpec(data.searchSpecJson);
      strategyParams = parseJsonObject(data.strategyParamsJson, "Strategy params");
    } catch (err) {
      setServerError(err instanceof Error ? err.message : "Invalid JSON input");
      return;
    }

    const trimmedSweepId = data.sweepId.trim();
    const body: SweepRunRequest = {
      strategy_name: data.strategy_name.trim(),
      symbols,
      start: toShanghaiStart(data.startDate),
      end: toShanghaiEnd(data.endDate),
      initial_cash: data.initialCash,
      freq: data.freq.trim(),
      bar_loader: data.barLoader as BacktestBarLoader,
      max_attempts: data.maxAttempts,
      search_type: "grid",
      search_spec: searchSpec,
      select_metric: data.selectMetric.trim(),
      maximize: data.maximize,
      fail_fast: data.failFast,
      strategy_params: strategyParams,
    };
    if (trimmedSweepId) {
      body.sweep_id = trimmedSweepId;
    }
    mutation.mutate(body);
  };

  return (
    <div style={{ maxWidth: 820, margin: "24px auto" }}>
      <div style={{ marginBottom: 16 }}>
        <Link to="/backtests" style={{ fontSize: 13 }}>
          ← Back to Backtests
        </Link>
      </div>

      <h1 className="section-title">New Sweep</h1>
      <p className="text-muted" style={{ marginBottom: 24, fontSize: 13 }}>
        Submit a grid-search parameter sweep. Completed jobs link to the sweep result page.
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

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 16 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label htmlFor="selectMetric" style={{ fontWeight: 500, fontSize: 13 }}>
              Select Metric *
            </label>
            <input id="selectMetric" list="metric-options" style={fieldStyle} {...register("selectMetric")} />
            <datalist id="metric-options">
              {METRIC_OPTIONS.map((metric) => (
                <option key={metric} value={metric} />
              ))}
            </datalist>
            <FieldError message={errors.selectMetric?.message} />
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
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label htmlFor="sweepId" style={{ fontWeight: 500, fontSize: 13 }}>
              Sweep ID
            </label>
            <input id="sweepId" style={fieldStyle} placeholder="Optional explicit ID" {...register("sweepId")} />
            <FieldError message={errors.sweepId?.message} />
          </div>
        </div>

        <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
            <input type="checkbox" {...register("maximize")} />
            Maximize selected metric
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
            <input type="checkbox" {...register("failFast")} />
            Stop on first failed trial
          </label>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label htmlFor="searchSpecJson" style={{ fontWeight: 500, fontSize: 13 }}>
            Search Spec JSON *
          </label>
          <textarea
            id="searchSpecJson"
            rows={9}
            style={{ ...fieldStyle, fontFamily: "var(--font-mono, monospace)", resize: "vertical" }}
            {...register("searchSpecJson")}
          />
          <span className="text-muted" style={{ fontSize: 12 }}>
            Must be a JSON object with a non-empty <code>space</code> object. Grid search accepts
            literal arrays or parameter specs compatible with the backend.
          </span>
          <FieldError message={errors.searchSpecJson?.message} />
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label htmlFor="strategyParamsJson" style={{ fontWeight: 500, fontSize: 13 }}>
            Base Strategy Params JSON
          </label>
          <textarea
            id="strategyParamsJson"
            rows={5}
            style={{ ...fieldStyle, fontFamily: "var(--font-mono, monospace)", resize: "vertical" }}
            {...register("strategyParamsJson")}
          />
          <span className="text-muted" style={{ fontSize: 12 }}>
            Optional base params merged with each trial, for example {`{"symbol": "000001.SZ"}`}.
          </span>
        </div>

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
            {mutation.isPending ? "Creating…" : "Create Sweep"}
          </button>
        </div>
      </form>
    </div>
  );
}
