import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useState } from "react";
import { listStrategies, type StrategySummary } from "../api/strategies";
import { subscribe, unsubscribe } from "../api/subscriptions";
import { ApiClientError } from "../api/client";

/** Inline subscription button + status for a single strategy row. */
function SubscriptionCell({ s }: { s: StrategySummary }) {
  const queryClient = useQueryClient();
  const [planType, setPlanType] = useState<"monthly" | "yearly">("monthly");
  const [showPicker, setShowPicker] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; msg: string } | null>(
    null,
  );

  const subscribeMut = useMutation({
    mutationFn: () =>
      subscribe(s.id, { plan_type: planType, payment_source: "wechat", auto_renew: true }),
    onSuccess: (res) => {
      setFeedback({
        type: "success",
        msg: `Subscribed! Order: ${res.data.payment.order_id}`,
      });
      setShowPicker(false);
      queryClient.invalidateQueries({ queryKey: ["strategies"] });
    },
    onError: (err: unknown) => {
      setFeedback({
        type: "error",
        msg: err instanceof ApiClientError ? err.detail : "Subscribe failed",
      });
    },
  });

  const unsubscribeMut = useMutation({
    mutationFn: () => unsubscribe(s.id),
    onSuccess: () => {
      setFeedback({ type: "success", msg: "Unsubscribed — access retained until period end." });
      queryClient.invalidateQueries({ queryKey: ["strategies"] });
    },
    onError: (err: unknown) => {
      setFeedback({
        type: "error",
        msg: err instanceof ApiClientError ? err.detail : "Unsubscribe failed",
      });
    },
  });

  const price = s.subscription_price;
  const priceLabel =
    price.monthly > 0
      ? `¥${price.monthly}/mo`
      : price.yearly > 0
        ? `¥${price.yearly}/yr`
        : "Free";

  if (s.is_subscribed) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 140 }}>
        <span style={{ fontSize: 12, color: "var(--success, #22c55e)", fontWeight: 600 }}>
          ✓ Subscribed
        </span>
        <button
          onClick={() => {
            setFeedback(null);
            unsubscribeMut.mutate();
          }}
          disabled={unsubscribeMut.isPending}
          style={{
            padding: "2px 10px",
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

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 160 }}>
      <span style={{ fontSize: 12, fontWeight: 600 }}>{priceLabel}</span>
      {!showPicker ? (
        <button
          onClick={() => {
            setFeedback(null);
            setShowPicker(true);
          }}
          disabled={subscribeMut.isPending}
          style={{
            padding: "2px 10px",
            border: "1px solid var(--primary)",
            borderRadius: "var(--radius)",
            background: "var(--primary)",
            color: "var(--primary-foreground)",
            fontSize: 12,
            cursor: subscribeMut.isPending ? "not-allowed" : "pointer",
          }}
        >
          {subscribeMut.isPending ? "…" : "Subscribe"}
        </button>
      ) : (
        <div style={{ display: "flex", gap: 4, alignItems: "center", flexWrap: "wrap" }}>
          <select
            value={planType}
            onChange={(e) => setPlanType(e.target.value as "monthly" | "yearly")}
            style={{
              padding: "2px 4px",
              border: "1px solid var(--border)",
              borderRadius: 4,
              fontSize: 11,
              background: "var(--card-bg)",
            }}
          >
            <option value="monthly">Monthly ¥{price.monthly}</option>
            <option value="yearly">Yearly ¥{price.yearly}</option>
          </select>
          <button
            onClick={() => subscribeMut.mutate()}
            disabled={subscribeMut.isPending}
            style={{
              padding: "2px 8px",
              border: "none",
              borderRadius: 4,
              background: "var(--primary)",
              color: "var(--primary-foreground)",
              fontSize: 11,
              cursor: subscribeMut.isPending ? "not-allowed" : "pointer",
            }}
          >
            OK
          </button>
          <button
            onClick={() => setShowPicker(false)}
            style={{
              padding: "2px 8px",
              border: "1px solid var(--border)",
              borderRadius: 4,
              background: "transparent",
              fontSize: 11,
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

export default function Strategies() {
  const { data: strategies, isLoading, error } = useQuery({
    queryKey: ["strategies"],
    queryFn: listStrategies,
  });

  return (
    <div>
      <h1 className="section-title">Strategies</h1>

      {isLoading && <div className="loading">Loading…</div>}
      {error && (
        <div className="error-box">
          {error instanceof Error ? error.message : "Unknown error"}
        </div>
      )}

      {strategies && (
        <div className="card">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Code</th>
                <th>Subscribers</th>
                <th>Subscription</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {strategies.length === 0 ? (
                <tr>
                  <td colSpan={5} className="text-muted" style={{ textAlign: "center" }}>
                    No strategies found
                  </td>
                </tr>
              ) : (
                strategies.map((s: StrategySummary) => (
                  <tr key={s.id}>
                    <td>
                      <Link
                        to={`/strategies/${encodeURIComponent(s.id)}`}
                        style={{ color: "var(--primary)", fontWeight: 500 }}
                      >
                        {s.name}
                      </Link>
                    </td>
                    <td style={{ fontFamily: "monospace", fontSize: 12 }}>{s.id}</td>
                    <td>{s.subscriber_count}</td>
                    <td>
                      <SubscriptionCell s={s} />
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 8 }}>
                        <Link to={`/strategies/${encodeURIComponent(s.id)}/edit`}>
                          Edit
                        </Link>
                        <Link to={`/signals?strategy=${encodeURIComponent(s.id)}`}>
                          Signals
                        </Link>
                        <Link to={`/trades?strategy=${encodeURIComponent(s.id)}`}>
                          Trades
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
