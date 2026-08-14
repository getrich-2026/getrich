import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useState } from "react";
import {
  getStrategyDetail,
  updateStrategy,
  type StrategyUpdateFields,
} from "../api/strategies";
import { apiFetch, type ApiResponse, ApiClientError } from "../api/client";

// ---------------------------------------------------------------------------
// Form schema
// ---------------------------------------------------------------------------

const editSchema = z.object({
  name: z.string().min(1, "Name is required").max(128),
  description: z.string().default(""),
  // `detail_html` carries the user-supplied rich content rendered in
  // `frontend/src/pages/StrategyDetail.tsx`. Capped at 50,000 chars to
  // match the Pydantic `Field(max_length=50_000)` in
  // `apps/web/routers/strategies.py`, the bleach truncation in
  // `apps/web/services/sanitize.py`, and the Postgres `CHECK`
  // constraint in `migrations/024_*.sql`. The same 50K cap applies on
  // the service side, the schema side, and the backend Pydantic side;
  // the form is the *first* line of defense and rejects oversize
  // inputs before they hit the wire.
  detail_html: z
    .string()
    .max(50_000, "Detail HTML is too long (max 50,000 chars)")
    .default(""),
  category_id: z.string().default(""),
  asset_class: z.string().default(""),
  market: z.string().default(""),
  risk_level: z.string().default(""),
  run_status: z.enum(["paper", "live", "paused"]).default("paper"),
  subscription_monthly: z.number().min(0).default(0),
  subscription_yearly: z.number().min(0).default(0),
  backtest_start: z.string().default(""),
  backtest_end: z.string().default(""),
});

type EditFormValues = z.infer<typeof editSchema>;

interface CategoryItem {
  id: string;
  name: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ASSET_CLASSES = ["stock", "future", "option", "crypto", "forex", "multi"];
const MARKETS = ["CN", "US", "HK", "global"];
const RISK_LEVELS = ["low", "medium", "high"];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function StrategyEdit() {
  const { code } = useParams<{ code: string }>();
  const navigate = useNavigate();
  const [serverError, setServerError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  // Fetch categories for dropdown
  const { data: categories } = useQuery({
    queryKey: ["categories"],
    queryFn: () =>
      apiFetch<ApiResponse<{ categories: CategoryItem[] }>>("/strategies/categories"),
  });

  // Fetch strategy detail to pre-populate form
  const {
    data: detail,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["strategy-detail", code],
    queryFn: () => getStrategyDetail(code!),
    enabled: !!code,
  });

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting, isDirty },
  } = useForm({
    resolver: zodResolver(editSchema),
    defaultValues: {
      name: "",
      description: "",
      detail_html: "",
      category_id: "",
      asset_class: "",
      market: "",
      risk_level: "",
      run_status: "paper" as const,
      subscription_monthly: 0,
      subscription_yearly: 0,
      backtest_start: "",
      backtest_end: "",
    },
  });

  // Pre-populate form when detail loads
  const [formReady, setFormReady] = useState(false);
  if (detail && !formReady) {
    const d = detail.data;
    reset({
      name: d.name ?? "",
      description: d.description ?? "",
      detail_html: d.detail_html ?? "",
      category_id: d.category?.id ?? "",
      asset_class: d.asset_class ?? "",
      market: d.market ?? "",
      risk_level: d.risk_level ?? "",
      run_status: (d.status === "active" ? "paper" : "paused") as "paper" | "live" | "paused",
      subscription_monthly: d.subscription_price?.monthly ?? 0,
      subscription_yearly: d.subscription_price?.yearly ?? 0,
      backtest_start: d.backtest_period?.start ?? "",
      backtest_end: d.backtest_period?.end ?? "",
    });
    setFormReady(true);
  }

  const mutation = useMutation({
    mutationFn: (body: StrategyUpdateFields) => updateStrategy(code!, body),
    onSuccess: () => {
      setSaved(true);
      setServerError(null);
      setTimeout(() => setSaved(false), 2500);
    },
    onError: (err) => {
      if (err instanceof ApiClientError) {
        setServerError(err.detail);
      } else {
        setServerError("Failed to save — is the API server running?");
      }
    },
  });

  const onSubmit = async (data: EditFormValues) => {
    setServerError(null);
    setSaved(false);

    const body: StrategyUpdateFields = {
      name: data.name,
      description: data.description || "",
      detail_html: data.detail_html || "",
      category_id: data.category_id || undefined,
      asset_class: data.asset_class || undefined,
      market: data.market || undefined,
      risk_level: data.risk_level || undefined,
      run_status: data.run_status,
      subscription_monthly: data.subscription_monthly,
      subscription_yearly: data.subscription_yearly,
      backtest_start: data.backtest_start || undefined,
      backtest_end: data.backtest_end || undefined,
    };
    // Remove empty string fields that should be null
    Object.keys(body).forEach((k) => {
      const key = k as keyof StrategyUpdateFields;
      if (body[key] === "" || body[key] === undefined) {
        delete body[key];
      }
    });

    mutation.mutate(body);
  };

  // -----------------------------------------------------------------------
  // Loading / error states
  // -----------------------------------------------------------------------

  if (isLoading) {
    return (
      <div style={{ maxWidth: 640, margin: "32px auto" }}>
        <div className="loading">Loading strategy…</div>
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div style={{ maxWidth: 640, margin: "32px auto" }}>
        <div className="error-box">
          {error instanceof Error ? error.message : "Strategy not found"}
        </div>
        <button
          onClick={() => navigate("/strategies")}
          style={{
            marginTop: 16,
            padding: "8px 16px",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius)",
            background: "var(--background)",
            color: "var(--foreground)",
            cursor: "pointer",
          }}
        >
          ← Back to Strategies
        </button>
      </div>
    );
  }

  // -----------------------------------------------------------------------
  // Form
  // -----------------------------------------------------------------------

  const catList = categories?.data?.categories ?? [];

  const fieldStyle: React.CSSProperties = {
    padding: "8px 12px",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius)",
    fontSize: 14,
    background: "var(--background)",
    color: "var(--foreground)",
  };

  return (
    <div style={{ maxWidth: 640, margin: "32px auto" }}>
      <h1 className="section-title">Edit Strategy</h1>
      <p className="text-muted" style={{ marginBottom: 24 }}>
        Editing <strong>{code}</strong>
      </p>

      <form
        onSubmit={handleSubmit(onSubmit)}
        style={{ display: "flex", flexDirection: "column", gap: 16 }}
      >
        {/* Server error banner */}
        {serverError && (
          <div
            style={{
              padding: "8px 12px",
              borderRadius: "var(--radius)",
              background: "var(--danger)",
              color: "var(--danger-foreground, #fff)",
              fontSize: 13,
            }}
          >
            {serverError}
          </div>
        )}

        {/* Saved banner */}
        {saved && (
          <div
            style={{
              padding: "8px 12px",
              borderRadius: "var(--radius)",
              background: "var(--success, #16a34a)",
              color: "#fff",
              fontSize: 13,
            }}
          >
            Strategy updated successfully!
          </div>
        )}

        {/* Name */}
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label htmlFor="name" style={{ fontWeight: 500, fontSize: 13 }}>
            Name *
          </label>
          <input id="name" {...register("name")} style={fieldStyle} />
          {errors.name && (
            <span style={{ color: "var(--danger)", fontSize: 12 }}>
              {errors.name.message}
            </span>
          )}
        </div>

        {/* Description */}
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label htmlFor="description" style={{ fontWeight: 500, fontSize: 13 }}>
            Description
          </label>
          <textarea
            id="description"
            {...register("description")}
            rows={3}
            style={{ ...fieldStyle, resize: "vertical" }}
          />
        </div>

        {/* Category + Risk Level (row) */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label htmlFor="category_id" style={{ fontWeight: 500, fontSize: 13 }}>
              Category
            </label>
            <select id="category_id" {...register("category_id")} style={fieldStyle}>
              <option value="">— None —</option>
              {catList.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label htmlFor="risk_level" style={{ fontWeight: 500, fontSize: 13 }}>
              Risk Level
            </label>
            <select id="risk_level" {...register("risk_level")} style={fieldStyle}>
              <option value="">— Not set —</option>
              {RISK_LEVELS.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Asset Class + Market (row) */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label htmlFor="asset_class" style={{ fontWeight: 500, fontSize: 13 }}>
              Asset Class
            </label>
            <select id="asset_class" {...register("asset_class")} style={fieldStyle}>
              <option value="">— Not set —</option>
              {ASSET_CLASSES.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label htmlFor="market" style={{ fontWeight: 500, fontSize: 13 }}>
              Market
            </label>
            <select id="market" {...register("market")} style={fieldStyle}>
              <option value="">— Not set —</option>
              {MARKETS.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Run Status */}
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label htmlFor="run_status" style={{ fontWeight: 500, fontSize: 13 }}>
            Run Status
          </label>
          <select id="run_status" {...register("run_status")} style={fieldStyle}>
            <option value="paper">Paper</option>
            <option value="live">Live</option>
            <option value="paused">Paused</option>
          </select>
        </div>

        {/* Subscription Prices (row) */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label htmlFor="subscription_monthly" style={{ fontWeight: 500, fontSize: 13 }}>
              Monthly Price (¥)
            </label>
            <input
              id="subscription_monthly"
              type="number"
              step="0.01"
              min="0"
              {...register("subscription_monthly", { valueAsNumber: true })}
              style={fieldStyle}
            />
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label htmlFor="subscription_yearly" style={{ fontWeight: 500, fontSize: 13 }}>
              Yearly Price (¥)
            </label>
            <input
              id="subscription_yearly"
              type="number"
              step="0.01"
              min="0"
              {...register("subscription_yearly", { valueAsNumber: true })}
              style={fieldStyle}
            />
          </div>
        </div>

        {/* Backtest Period (row) */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label htmlFor="backtest_start" style={{ fontWeight: 500, fontSize: 13 }}>
              Backtest Start
            </label>
            <input
              id="backtest_start"
              type="date"
              {...register("backtest_start")}
              style={fieldStyle}
            />
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label htmlFor="backtest_end" style={{ fontWeight: 500, fontSize: 13 }}>
              Backtest End
            </label>
            <input
              id="backtest_end"
              type="date"
              {...register("backtest_end")}
              style={fieldStyle}
            />
          </div>
        </div>

        {/* Detail HTML (rich text placeholder) */}
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label htmlFor="detail_html" style={{ fontWeight: 500, fontSize: 13 }}>
            Detail HTML
          </label>
          <textarea
            id="detail_html"
            {...register("detail_html")}
            rows={6}
            style={{ ...fieldStyle, resize: "vertical", fontFamily: "monospace", fontSize: 12 }}
          />
        </div>

        {/* Actions */}
        <div style={{ display: "flex", gap: 12, marginTop: 8 }}>
          <button
            type="submit"
            disabled={isSubmitting || !isDirty}
            style={{
              padding: "10px 20px",
              border: "none",
              borderRadius: "var(--radius)",
              background: "var(--primary)",
              color: "var(--primary-foreground)",
              fontSize: 14,
              fontWeight: 600,
              cursor: isSubmitting || !isDirty ? "not-allowed" : "pointer",
              opacity: isSubmitting || !isDirty ? 0.6 : 1,
            }}
          >
            {isSubmitting ? "Saving…" : "Save Changes"}
          </button>
          <button
            type="button"
            onClick={() => navigate("/strategies")}
            style={{
              padding: "10px 20px",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              background: "var(--background)",
              color: "var(--foreground)",
              fontSize: 14,
              cursor: "pointer",
            }}
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}
