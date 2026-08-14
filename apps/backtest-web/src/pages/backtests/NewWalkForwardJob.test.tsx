import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { BacktestJobCreateResponse, WalkForwardRunRequest } from "../../api/backtests";
import { createWalkForwardJob } from "../../api/backtests";
import { listStrategies } from "../../api/strategies";
import NewWalkForwardJob from "./NewWalkForwardJob";

vi.mock("../../api/backtests", async () => {
  const actual = await vi.importActual<typeof import("../../api/backtests")>("../../api/backtests");
  return {
    ...actual,
    createWalkForwardJob: vi.fn(),
  };
});

vi.mock("../../api/strategies", () => ({
  listStrategies: vi.fn(),
}));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <NewWalkForwardJob />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("NewWalkForwardJob", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listStrategies).mockResolvedValue([
      {
        id: "strategy-1",
        name: "MA Cross",
        code: "MACross",
        subscriber_count: 0,
        is_subscribed: false,
        subscription_price: { monthly: 0, yearly: 0 },
      },
    ]);
    vi.mocked(createWalkForwardJob).mockResolvedValue({
      job_id: "job-wf",
      ref_id: "wf-1",
      status: "queued",
    } satisfies BacktestJobCreateResponse);
  });

  it("submits a typed walk-forward creation request", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText(/Strategy Name/i), "MACross");
    await user.type(screen.getByLabelText(/Start Date/i), "2026-01-01");
    await user.type(screen.getByLabelText(/End Date/i), "2026-12-31");
    await user.click(screen.getByRole("button", { name: /Create Walk-forward/i }));

    await waitFor(() => expect(createWalkForwardJob).toHaveBeenCalledTimes(1));
    const [body, idempotencyKey] = vi.mocked(createWalkForwardJob).mock.calls[0] as [
      WalkForwardRunRequest,
      string,
    ];

    expect(idempotencyKey).toMatch(/[0-9a-f-]{36}/i);
    expect(body).toMatchObject({
      strategy_name: "MACross",
      symbols: ["000001.SZ"],
      start: "2026-01-01T00:00:00+08:00",
      end: "2026-12-31T23:59:59+08:00",
      initial_cash: "1000000",
      freq: "1d",
      bar_loader: "pg",
      max_attempts: 1,
      train_months: 12,
      val_months: 3,
      step_months: 3,
      refit: "rolling",
      select_metric: "sharpe_ratio",
      maximize: true,
      fail_fast: false,
      strategy_params: {},
    });
    expect(body.search_spec).toEqual({
      space: { fast: [5, 10], slow: [20, 60] },
      constraints: [],
    });
  });

  it("validates search spec JSON before submitting", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText(/Strategy Name/i), "MACross");
    await user.type(screen.getByLabelText(/Start Date/i), "2026-01-01");
    await user.type(screen.getByLabelText(/End Date/i), "2026-12-31");
    const searchSpec = screen.getByLabelText(/Search Spec JSON/i);
    fireEvent.change(searchSpec, { target: { value: JSON.stringify({ constraints: [] }) } });
    await user.click(screen.getByRole("button", { name: /Create Walk-forward/i }));

    expect(await screen.findByText(/Search spec must include a JSON object field named space/i)).toBeInTheDocument();
    expect(createWalkForwardJob).not.toHaveBeenCalled();
  });
});
