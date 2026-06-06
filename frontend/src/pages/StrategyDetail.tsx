import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { getStrategyDetail, type StrategyDetail } from "../api/strategies";
import { subscribe, unsubscribe } from "../api/subscriptions";
import { ApiClientError } from "../api/client";
import { sanitizeHtml } from "../lib/sanitize";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtPct(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${(n * 100).toFixed(2)}%`;
}

function fmtNum(n: number | null | undefined, decimals = 2): string {
  if (n == null) return "—";
  return n.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString();
}

// ---------------------------------------------------------------------------
// Subscription button (reused pattern from Strategies page)
// ---------------------------------------------------------------------------

function SubscribeButton({ strategy }: { strategy: StrategyDetail }) {
  const queryClient = useQueryClient();
  const [planType, setPlanType] = useState<"monthly" | "yearly">("monthly");
  const [showPicker, setShowPicker] = useState(false);
  const [feedback, setFeedback] = useState<{
    type: "success" | "error";
    msg: string;
  } | null>(null);

  const price = strategy.subscription_price;

  const subscribeMut = useMutation({
    mutationFn: () =>
      subscribe(strategy.id, {
        plan_type: planType,
        payment_source: "wechat",
        auto_renew: true,
      }),
    onSuccess: (res) => {
      setFeedback({
        type: "success",
        msg: `Subscribed! Order: ${res.data.payment.order_id}`,
      });
      setShowPicker(false);
      queryClient.invalidateQueries({ queryKey: ["strategy-detail", strategy.id] });
    },
    onError: (err: unknown) => {
      setFeedback({
        type: "error",
        msg: err instanceof ApiClientError ? err.detail : "Subscribe failed",
      });
    },
  });

  const unsubscribeMut = useMutation({
    mutationFn: () => unsubscribe(strategy.id),
    onSuccess: () => {
      setFeedback({
        type: "success",
        msg: "Unsubscribed — access retained until period end.",
      });
      queryClient.invalidateQueries({ queryKey: ["strategy-detail", strategy.id] });
    },
    onError: (err: unknown) => {
      setFeedback({
        type: "error",
        msg: err instanceof ApiClientError ? err.detail : "Unsubscribe failed",
      });
    },
  });

  if (strategy.is_subscribed) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-end" }}>
        <span style={{ fontSize: 13, color: "var(--success, #22c55e)", fontWeight: 600 }}>
          ✓ Subscribed
        </span>
        {strategy.subscription_info && (() => {
          const info = strategy.subscription_info as Record<string, string>;
          return (
            <span style={{ fontSize: 11, color: "var(--muted-foreground)" }}>
              {info.plan_type} · expires {fmtDate(info.expire_date)}
            </span>
          );
        })()}
        <button
          onClick={() => {
            setFeedback(null);
            unsubscribeMut.mutate();
          }}
          disabled={unsubscribeMut.isPending}
          style={{
            padding: "4px 14px",
            border: "1px solid var(--danger)",
            borderRadius: "var(--radius)",
            background: "transparent",
            color: "var(--danger)",
            fontSize: 12,
            cursor: unsubscribeMut.isPending ? "not-allowed" : "pointer",
          }}
        >
          {unsubscribeMut.isPending ? "…" : "Unsubscribe"}
        </button>
        {feedback && (
          <span
            style={{
              fontSize: 11,
              color: feedback.type === "success" ? "var(--success, #22c55e)" : "var(--danger)",
            }}
          >
            {feedback.msg}
          </span>
        )}
      </div>
    );
  }

  const priceLabel =
    price.monthly > 0
      ? `¥${price.monthly}/mo`
      : price.yearly > 0
        ? `¥${price.yearly}/yr`
        : "Free";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-end" }}>
      <span style={{ fontSize: 15, fontWeight: 700 }}>{priceLabel}</span>
      {!showPicker ? (
        <button
          onClick={() => {
            setFeedback(null);
            setShowPicker(true);
          }}
          disabled={subscribeMut.isPending}
          style={{
            padding: "8px 22px",
            border: "none",
            borderRadius: "var(--radius)",
            background: "var(--primary)",
            color: "var(--primary-foreground)",
            fontSize: 14,
            fontWeight: 600,
            cursor: subscribeMut.isPending ? "not-allowed" : "pointer",
          }}
        >
          {subscribeMut.isPending ? "…" : "Subscribe"}
        </button>
      ) : (
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <select
            value={planType}
            onChange={(e) => setPlanType(e.target.value as "monthly" | "yearly")}
            style={{
              padding: "4px 8px",
              border: "1px solid var(--border)",
              borderRadius: 4,
              fontSize: 12,
              background: "var(--card-bg)",
              color: "var(--foreground)",
            }}
          >
            <option value="monthly">Monthly ¥{price.monthly}</option>
            <option value="yearly">Yearly ¥{price.yearly}</option>
          </select>
          <button
            onClick={() => subscribeMut.mutate()}
            disabled={subscribeMut.isPending}
            style={{
              padding: "4px 12px",
              border: "none",
              borderRadius: 4,
              background: "var(--primary)",
              color: "var(--primary-foreground)",
              fontSize: 12,
              cursor: subscribeMut.isPending ? "not-allowed" : "pointer",
            }}
          >
            OK
          </button>
          <button
            onClick={() => setShowPicker(false)}
            style={{
              padding: "4px 8px",
              border: "1px solid var(--border)",
              borderRadius: 4,
              background: "transparent",
              fontSize: 12,
              cursor: "pointer",
            }}
          >
            ✕
          </button>
        </div>
      )}
      {feedback && (
        <span
          style={{
            fontSize: 11,
            color: feedback.type === "success" ? "var(--success, #22c55e)" : "var(--danger)",
          }}
        >
          {feedback.msg}
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Metric card
// ---------------------------------------------------------------------------

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
    <div
      className="card card-stat"
      style={{ textAlign: "center", minWidth: 120 }}
    >
      <div className="lbl">{label}</div>
      <div className="val" style={color ? { color } : undefined}>
        {value}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function StrategyDetailPage() {
  const { code } = useParams<{ code: string }>();
  const navigate = useNavigate();

  const {
    data: res,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["strategy-detail", code],
    queryFn: () => getStrategyDetail(code!),
    enabled: !!code,
  });

  const strategy = res?.data;

  // ---- render ----

  if (isLoading) {
    return (
      <div style={{ maxWidth: 800, margin: "24px auto" }}>
        <div className="loading">Loading strategy…</div>
      </div>
    );
  }

  if (error || !strategy) {
    return (
      <div style={{ maxWidth: 800, margin: "24px auto" }}>
        <div className="error-box">
          {error instanceof Error ? error.message : "Strategy not found"}
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

  const perf = strategy.performance;
  const bp = strategy.backtest_period;

  return (
    <div style={{ maxWidth: 800, margin: "24px auto" }}>
      {/* Back link */}
      <Link
        to="/strategies"
        style={{
          fontSize: 13,
          color: "var(--muted-foreground)",
          textDecoration: "none",
          marginBottom: 12,
          display: "inline-block",
        }}
      >
        ← Back to Strategies
      </Link>

      {/* Header row */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 16,
          marginBottom: 20,
        }}
      >
        <div>
          <h1 className="section-title" style={{ margin: 0 }}>
            {strategy.name}
          </h1>
          <div
            style={{
              display: "flex",
              gap: 8,
              marginTop: 8,
              flexWrap: "wrap",
              alignItems: "center",
            }}
          >
            <span
              style={{
                padding: "2px 10px",
                borderRadius: 999,
                fontSize: 11,
                fontWeight: 600,
                backgroundColor:
                  strategy.status === "active"
                    ? "var(--success, #22c55e)"
                    : "var(--muted)",
                color: strategy.status === "active" ? "#fff" : "var(--muted-foreground)",
              }}
            >
              {strategy.status.toUpperCase()}
            </span>
            <span style={{ fontSize: 13, color: "var(--muted-foreground)" }}>
              {strategy.asset_class} · {strategy.market} · {strategy.risk_level} risk
            </span>
            <span style={{ fontSize: 13, color: "var(--muted-foreground)" }}>
              {strategy.subscriber_count} subscriber{strategy.subscriber_count !== 1 ? "s" : ""}
            </span>
          </div>
          {/* Tags */}
          {strategy.tags.length > 0 && (
            <div style={{ display: "flex", gap: 4, marginTop: 8, flexWrap: "wrap" }}>
              {strategy.tags.map((t) => (
                <span
                  key={t}
                  style={{
                    padding: "1px 8px",
                    borderRadius: 999,
                    fontSize: 11,
                    background: "var(--muted)",
                    color: "var(--muted-foreground)",
                  }}
                >
                  {t}
                </span>
              ))}
            </div>
          )}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <SubscribeButton strategy={strategy} />
          <Link
            to={`/strategies/${encodeURIComponent(strategy.id)}/edit`}
            style={{
              padding: "4px 14px",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              background: "transparent",
              color: "var(--muted-foreground)",
              fontSize: 12,
              textDecoration: "none",
              textAlign: "center",
            }}
          >
            Edit
          </Link>
        </div>
      </div>

      {/* Performance metrics */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>Performance</h2>
        <div className="card-grid">
          <MetricCard label="Annualized Return" value={fmtPct(perf.annualized_return)} />
          <MetricCard label="Total Return" value={fmtPct(perf.total_return)} />
          <MetricCard
            label="Max Drawdown"
            value={fmtPct(perf.max_drawdown)}
            color="var(--danger)"
          />
          <MetricCard label="Sharpe Ratio" value={fmtNum(perf.sharpe_ratio)} />
          <MetricCard label="Sortino Ratio" value={fmtNum(perf.sortino_ratio)} />
          <MetricCard label="Win Rate" value={fmtPct(perf.win_rate)} />
          <MetricCard label="Total Trades" value={String(perf.total_trades ?? "—")} />
        </div>

        {/* Backtest period */}
        <div
          style={{
            marginTop: 12,
            fontSize: 12,
            color: "var(--muted-foreground)",
            textAlign: "center",
          }}
        >
          Backtest period: {fmtDate(bp.start)} — {fmtDate(bp.end)}
        </div>
      </div>

      {/* Category */}
      {strategy.category.name && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>Category</h2>
          <span
            style={{
              padding: "4px 12px",
              borderRadius: "var(--radius)",
              background: "var(--muted)",
              fontSize: 13,
            }}
          >
            {strategy.category.name}
          </span>
        </div>
      )}

      {/* Description */}
      {strategy.description && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>Description</h2>
          <p style={{ fontSize: 13, whiteSpace: "pre-wrap", lineHeight: 1.6 }}>
            {strategy.description}
          </p>
        </div>
      )}

      {/* Detail HTML — rich content from strategy author.
          Sanitized at the call site via `sanitizeHtml()` (see
          frontend/src/lib/sanitize.ts) which strips dangerous tags,
          event-handler attributes, and unsafe URI protocols. The custom
          local ESLint rule `no-unsanitized-danger` would flag this
          line if the sanitizer were bypassed. */}
      {strategy.detail_html && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>Strategy Detail</h2>
          <div
            className="detail-html"
            dangerouslySetInnerHTML={{ __html: sanitizeHtml(strategy.detail_html) }}
            style={{ fontSize: 13, lineHeight: 1.7 }}
          />
        </div>
      )}

      {/* Creator */}
      {strategy.creator.id && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>Creator</h2>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div
              style={{
                width: 36,
                height: 36,
                borderRadius: "50%",
                background: "var(--muted)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 14,
                fontWeight: 600,
                color: "var(--muted-foreground)",
              }}
            >
              {strategy.creator.name?.charAt(0) || "?"}
            </div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600 }}>
                {strategy.creator.name || strategy.creator.id}
              </div>
              {strategy.creator.bio && (
                <div style={{ fontSize: 12, color: "var(--muted-foreground)" }}>
                  {strategy.creator.bio}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Meta */}
      <div style={{ fontSize: 12, color: "var(--muted-foreground)", textAlign: "center" }}>
        Published {fmtDate(strategy.published_at)} · Updated {fmtDate(strategy.updated_at)}
      </div>
    </div>
  );
}
