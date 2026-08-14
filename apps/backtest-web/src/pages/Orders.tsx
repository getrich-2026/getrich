import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { listOrders, type OrderRecord } from "../api/orders";

const STATUS_OPTIONS = [
  { value: "all", label: "All" },
  { value: "pending", label: "Pending" },
  { value: "paid", label: "Paid" },
  { value: "cancelled", label: "Cancelled" },
  { value: "refunded", label: "Refunded" },
  { value: "failed", label: "Failed" },
];

const PAGE_SIZE = 10;

export default function Orders() {
  const [status, setStatus] = useState("all");
  const [page, setPage] = useState(0);

  const { data, isLoading, error } = useQuery({
    queryKey: ["orders", status, page],
    queryFn: () => listOrders({ status, page, limit: PAGE_SIZE }),
  });

  const orders: OrderRecord[] = data?.data?.list ?? [];
  const pagination = data?.data?.pagination;
  const totalPages = pagination?.total_pages ?? 0;

  function statusBadge(s: string) {
    const map: Record<string, { bg: string; fg: string }> = {
      pending: { bg: "var(--primary)", fg: "var(--primary-foreground)" },
      paid: { bg: "var(--success, #22c55e)", fg: "#fff" },
      cancelled: { bg: "var(--muted)", fg: "var(--muted-foreground)" },
      refunded: { bg: "#f97316", fg: "#fff" },
      failed: { bg: "var(--danger)", fg: "var(--danger-foreground, #fff)" },
    };
    const c = map[s] ?? { bg: "var(--muted)", fg: "var(--muted-foreground)" };
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
        {s.toUpperCase()}
      </span>
    );
  }

  return (
    <div>
      <h1 className="section-title">Orders</h1>

      {/* Status filter */}
      <div style={{ marginBottom: 16, display: "flex", gap: 6, flexWrap: "wrap" }}>
        {STATUS_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            onClick={() => {
              setStatus(opt.value);
              setPage(0);
            }}
            style={{
              padding: "4px 12px",
              fontSize: 12,
              fontWeight: 500,
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              background: status === opt.value ? "var(--primary)" : "var(--card-bg)",
              color:
                status === opt.value
                  ? "var(--primary-foreground)"
                  : "var(--foreground)",
              cursor: "pointer",
            }}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {isLoading && <div className="loading">Loading…</div>}
      {error && (
        <div className="error-box">
          {error instanceof Error ? error.message : "Unknown error"}
        </div>
      )}

      {data && orders.length === 0 && (
        <div className="card">
          <div className="text-muted" style={{ textAlign: "center", padding: 24 }}>
            No orders found.
          </div>
        </div>
      )}

      {data && orders.length > 0 && (
        <div className="card">
          <table>
            <thead>
              <tr>
                <th>Order #</th>
                <th>Status</th>
                <th>Items</th>
                <th>Amount</th>
                <th>Payment</th>
                <th>Created</th>
                <th>Paid</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.order_id}>
                  <td style={{ fontFamily: "monospace", fontSize: 12 }}>
                    {o.order_id}
                  </td>
                  <td>{statusBadge(o.status)}</td>
                  <td>
                    {o.items.length === 0 ? (
                      <span className="text-muted">—</span>
                    ) : (
                      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                        {o.items.map((item, idx) => (
                          <span key={idx} style={{ fontSize: 12 }}>
                            {item.item_name}
                            {item.plan_type && (
                              <span className="text-muted">
                                {" "}
                                ({item.plan_type})
                              </span>
                            )}
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td>¥{o.total_amount.toFixed(2)}</td>
                  <td style={{ fontSize: 12 }}>{o.payment_source}</td>
                  <td style={{ fontSize: 12 }}>
                    {new Date(o.created_at).toLocaleString()}
                  </td>
                  <td style={{ fontSize: 12 }}>
                    {o.paid_at ? new Date(o.paid_at).toLocaleString() : "—"}
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
          <button
            disabled={page >= totalPages - 1}
            onClick={() => setPage(page + 1)}
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
