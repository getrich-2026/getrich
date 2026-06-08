/** Tests for the Dashboard page. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getEquityCurve, listStrategies } from "../api/strategies";
import Dashboard from "./Dashboard";

vi.mock("../api/strategies", () => ({
  listStrategies: vi.fn(),
  getEquityCurve: vi.fn(),
}));

function renderDashboard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <Dashboard />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(listStrategies).mockReset();
  vi.mocked(getEquityCurve).mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Dashboard — empty state", () => {
  it("shows the empty message when no strategies exist", async () => {
    vi.mocked(listStrategies).mockResolvedValue([]);
    renderDashboard();
    await waitFor(() => {
      expect(screen.getByText(/no strategies configured yet/i)).toBeInTheDocument();
    });
  });
});

describe("Dashboard — error", () => {
  it("shows an error message when strategies fail to load", async () => {
    vi.mocked(listStrategies).mockRejectedValue(new Error("Network down"));
    renderDashboard();
    await waitFor(() => {
      expect(screen.getByText(/network down/i)).toBeInTheDocument();
    });
  });
});

describe("Dashboard — populated", () => {
  const STRATEGIES = [
    { id: "s-1", code: "STRAT_A", name: "Strategy A", subscriber_count: 0, is_subscribed: false, subscription_price: { monthly: 0, yearly: 0 } },
    { id: "s-2", code: "STRAT_B", name: "Strategy B", subscriber_count: 0, is_subscribed: false, subscription_price: { monthly: 0, yearly: 0 } },
  ];

  // Real EquityCurveData shape (see frontend/src/api/strategies.ts).
  // The full ApiResponse envelope (code/message/data/timestamp/request_id)
  // is required by the `getEquityCurve` return type.
  const EMPTY_CURVE = {
    code: 0,
    message: "ok",
    data: {
      strategy_id: "STRAT_A",
      period: { start: "2024-01-01", end: "2024-06-01" },
      equity_curve: [],
      benchmark_curve: [],
      drawdown_curve: [],
      total_points: 0,
    },
    timestamp: 0,
    request_id: "test",
  };

  it("renders a strategy option for each strategy and fetches the first one's curve", async () => {
    vi.mocked(listStrategies).mockResolvedValue(STRATEGIES);
    vi.mocked(getEquityCurve).mockResolvedValue(EMPTY_CURVE);
    renderDashboard();
    await waitFor(() => {
      expect(screen.getByRole("option", { name: /strategy a/i })).toBeInTheDocument();
    });
    expect(screen.getByRole("option", { name: /strategy b/i })).toBeInTheDocument();
    // The first strategy triggers the equity-curve query by default.
    await waitFor(() => {
      expect(getEquityCurve).toHaveBeenCalledWith("STRAT_A", { period: "6m" });
    });
  });

  it("switches to the second strategy's curve when the user picks it from the dropdown", async () => {
    vi.mocked(listStrategies).mockResolvedValue(STRATEGIES);
    vi.mocked(getEquityCurve).mockResolvedValue(EMPTY_CURVE);
    const user = userEvent.setup();
    renderDashboard();
    await waitFor(() => {
      expect(screen.getByRole("option", { name: /strategy a/i })).toBeInTheDocument();
    });
    // Change the picker to the second strategy.
    await user.selectOptions(screen.getByLabelText(/strategy:/i), screen.getByRole("option", { name: /strategy b/i }));
    await waitFor(() => {
      expect(getEquityCurve).toHaveBeenLastCalledWith("STRAT_B", { period: "6m" });
    });
  });
});
