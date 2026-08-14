import { useQuery } from "@tanstack/react-query";
import { useSearchParams, Link } from "react-router-dom";
import { useState } from "react";
import { listStrategies, listSignals, type SignalRecord } from "../api/strategies";

const PAGE_SIZE = 20;

export default function Signals() {
  const [searchParams] = useSearchParams();
  const strategyParam = searchParams.get("strategy") ?? "";
  const [selectedStrategy, setSelectedStrategy] = useState(strategyParam);
  const [page, setPage] = useState(0);

  // Fetch strategy list for the dropdown
  const { data: strategies } = useQuery({
    queryKey: ["strategies"],
    queryFn: listStrategies,
    staleTime: 60_000,
  });

  // Fetch signals for the selected strategy
  const { data, isLoading, error } = useQuery({
    queryKey: ["signals", selectedStrategy, page],
    queryFn: () =>
      listSignals(selectedStrategy, {
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
    enabled: !!selectedStrategy,
  });

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0;

  return (
    <div>
      <h1 className="section-title">Signals</h1>

      {/* Strategy selector */}
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
        <div className="text-muted">Select a strategy to view its signals.</div>
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
                  <th>ID</th>
                  <th>Time</th>
                  <th>Symbol</th>
                  <th>Type</th>
                  <th>Action</th>
                  <th>Price</th>
                  <th>Confidence</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {data.data.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="text-muted" style={{ textAlign: "center" }}>
                      No signals found
                    </td>
                  </tr>
                ) : (
                  data.data.map((sig: SignalRecord) => (
                    <tr key={sig.id}>
                      <td>
                        <Link
                          to={`/signals/${sig.id}`}
                          style={{ color: "var(--primary)", fontWeight: 500 }}
                        >
                          {sig.id}
                        </Link>
                      </td>
                      <td>{new Date(sig.trigger_time).toLocaleString()}</td>
                      <td>{sig.symbol}</td>
                      <td>{sig.signal_type}</td>
                      <td className={sig.action === "buy" ? "text-success" : "text-danger"}>
                        {sig.action}
                      </td>
                      <td>{sig.trigger_price}</td>
                      <td>{(sig.confidence * 100).toFixed(0)}%</td>
                      <td>
                        <span
                          style={{
                            padding: "2px 8px",
                            borderRadius: 999,
                            fontSize: 11,
                            fontWeight: 600,
                            backgroundColor:
                              sig.status === "active"
                                ? "var(--success, #22c55e)"
                                : "var(--muted)",
                            color:
                              sig.status === "active"
                                ? "#fff"
                                : "var(--muted-foreground)",
                          }}
                        >
                          {sig.status}
                        </span>
                      </td>
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
