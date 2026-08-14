import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { listStrategies, getEquityCurve } from "../api/strategies";
import EquityCurveChart from "../components/EquityCurveChart";

const PERIODS = [
  { value: "1m", label: "1M" },
  { value: "3m", label: "3M" },
  { value: "6m", label: "6M" },
  { value: "1y", label: "1Y" },
  { value: "3y", label: "3Y" },
  { value: "all", label: "All" },
];

export default function Dashboard() {
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [period, setPeriod] = useState("6m");

  const { data: strategies, isLoading, error } = useQuery({
    queryKey: ["strategies"],
    queryFn: listStrategies,
  });

  const selectedStrategy = strategies?.[selectedIdx];
  const strategyCode = selectedStrategy?.code;

  const { data: curveResp } = useQuery({
    queryKey: ["equity-curve", strategyCode, period],
    queryFn: () => getEquityCurve(strategyCode!, { period }),
    enabled: !!strategyCode,
  });

  const curveData = curveResp?.data;

  return (
    <div>
      <h1 className="section-title">Dashboard</h1>

      {isLoading && <div className="loading">Loading…</div>}
      {error && (
        <div className="error-box">
          {error instanceof Error ? error.message : "Unknown error"}
        </div>
      )}

      {strategies && strategies.length === 0 && (
        <div className="text-muted">No strategies configured yet.</div>
      )}

      {strategies && strategies.length > 0 && (
        <>
          {/* Strategy selector + period toggle */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              marginBottom: 16,
              flexWrap: "wrap",
            }}
          >
            <label htmlFor="strategy-picker" style={{ fontWeight: 500, fontSize: 14 }}>
              Strategy:
            </label>
            <select
              id="strategy-picker"
              value={selectedIdx}
              onChange={(e) => setSelectedIdx(Number(e.target.value))}
              style={{
                padding: "6px 12px",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius)",
                fontSize: 13,
                background: "var(--card)",
                color: "var(--foreground)",
                minWidth: 200,
              }}
            >
              {strategies.map((s, i) => (
                <option key={s.id} value={i}>
                  {s.name} ({s.code})
                </option>
              ))}
            </select>

            <div style={{ display: "flex", gap: 4 }}>
              {PERIODS.map((p) => (
                <button
                  key={p.value}
                  onClick={() => setPeriod(p.value)}
                  style={{
                    padding: "4px 10px",
                    fontSize: 12,
                    fontWeight: 500,
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius)",
                    background: period === p.value ? "var(--primary)" : "var(--card)",
                    color: period === p.value ? "var(--primary-foreground)" : "var(--foreground)",
                    cursor: "pointer",
                  }}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {/* Performance stat cards */}
          <div className="card-grid">
            {selectedStrategy && (
              <>
                <div className="card card-stat">
                  <div className="lbl">Strategy</div>
                  <div className="val" style={{ fontSize: 18 }}>
                    {selectedStrategy.name}
                  </div>
                </div>
              </>
            )}
            {curveData && (
              <>
                <div className="card card-stat">
                  <div className="lbl">Total Points</div>
                  <div className="val">{curveData.total_points}</div>
                </div>
                {curveData.equity_curve.length > 0 && (
                  <>
                    <div className="card card-stat">
                      <div className="lbl">Latest NAV</div>
                      <div className="val">
                        {curveData.equity_curve[
                          curveData.equity_curve.length - 1
                        ].nav.toFixed(4)}
                      </div>
                    </div>
                    <div className="card card-stat">
                      <div className="lbl">Cumulative Return</div>
                      <div
                        className="val"
                        style={{
                          color:
                            (curveData.equity_curve[
                              curveData.equity_curve.length - 1
                            ].cumulative_return ?? 0) >= 0
                              ? "var(--success)"
                              : "var(--danger)",
                        }}
                      >
                        {(
                          (curveData.equity_curve[
                            curveData.equity_curve.length - 1
                          ].cumulative_return ?? 0) * 100
                        ).toFixed(2)}
                        %
                      </div>
                    </div>
                  </>
                )}
              </>
            )}
          </div>

          {/* Equity curve chart */}
          <div className="card" style={{ marginTop: 4 }}>
            <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>
              Equity Curve
            </h2>
            {curveData && curveData.equity_curve.length > 0 ? (
              <EquityCurveChart
                equity={curveData.equity_curve}
                benchmark={curveData.benchmark_curve}
                drawdown={curveData.drawdown_curve}
              />
            ) : (
              <div className="text-muted" style={{ textAlign: "center", padding: 48 }}>
                No equity data available for this strategy.
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
