import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { useState } from "react";
import { listStrategies, listTrades, type TradeRecord } from "../api/strategies";

const PAGE_SIZE = 20;

export default function Trades() {
  const [searchParams] = useSearchParams();
  const strategyParam = searchParams.get("strategy") ?? "";
  const [selectedStrategy, setSelectedStrategy] = useState(strategyParam);
  const [page, setPage] = useState(0);

  const { data: strategies } = useQuery({
    queryKey: ["strategies"],
    queryFn: listStrategies,
    staleTime: 60_000,
  });

  const { data, isLoading, error } = useQuery({
    queryKey: ["trades", selectedStrategy, page],
    queryFn: () =>
      listTrades(selectedStrategy, {
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
    enabled: !!selectedStrategy,
  });

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0;

  return (
    <div>
      <h1 className="section-title">Trades</h1>

      <div style={{ marginBottom: 16 }}>
        <label htmlFor="strategy-select" style={{ marginRight: 8, fontWeight: 500 }}>
          Strategy:
        </label>
        <select
          id="strategy-select"
          value={selectedStrategy}
          onChange={(e) => {
            setSelectedStrategy(e.target.value);
            setPage(0);
          }}
          style={{
            padding: "6px 12px",
            border: "1px solid var(--border)",
            borderRadius: 6,
            fontSize: 13,
            background: "var(--card-bg)",
            minWidth: 200,
          }}
        >
          <option value="">-- Select a strategy --</option>
          {strategies?.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name} ({s.id})
            </option>
          ))}
        </select>
      </div>

      {!selectedStrategy && (
        <div className="text-muted">Select a strategy to view its trades.</div>
      )}

      {isLoading && <div className="loading">Loading…</div>}
      {error && (
        <div className="error-box">
          {error instanceof Error ? error.message : "Unknown error"}
        </div>
      )}

      {data && (
        <>
          <div className="card">
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Symbol</th>
                  <th>Action</th>
                  <th>Qty</th>
                  <th>Price</th>
                  <th>Notional</th>
                  <th>Fee</th>
                  <th>Avg Cost</th>
                  <th>Realized PnL</th>
                  <th>Cum. PnL</th>
                  <th>Tag</th>
                </tr>
              </thead>
              <tbody>
                {data.data.length === 0 ? (
                  <tr>
                    <td colSpan={11} className="text-muted" style={{ textAlign: "center" }}>
                      No trades found
                    </td>
                  </tr>
                ) : (
                  data.data.map((t: TradeRecord) => (
                    <tr key={t.id}>
                      <td>{new Date(t.executed_at).toLocaleString()}</td>
                      <td>{t.symbol}</td>
                      <td className={t.action === "buy" ? "text-success" : "text-danger"}>
                        {t.action}
                      </td>
                      <td>{t.quantity}</td>
                      <td>{t.price}</td>
                      <td>{t.notional.toLocaleString()}</td>
                      <td>{t.fee}</td>
                      <td>{t.avg_cost !== null ? t.avg_cost.toFixed(4) : "—"}</td>
                      <td
                        className={
                          t.realized_pnl > 0
                            ? "text-success"
                            : t.realized_pnl < 0
                              ? "text-danger"
                              : ""
                        }
                      >
                        {t.realized_pnl.toFixed(2)}
                      </td>
                      <td
                        className={
                          (t.cumulative_pnl ?? 0) > 0
                            ? "text-success"
                            : (t.cumulative_pnl ?? 0) < 0
                              ? "text-danger"
                              : ""
                        }
                      >
                        {t.cumulative_pnl !== null ? t.cumulative_pnl.toFixed(2) : "—"}
                      </td>
                      <td>{t.tag ?? "—"}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="pagination">
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
        </>
      )}
    </div>
  );
}
