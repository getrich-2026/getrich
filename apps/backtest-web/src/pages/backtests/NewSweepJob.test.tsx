/** Tests for the New Sweep form page. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  BacktestJobCreateResponse,
  SweepRunRequest,
} from "../../api/backtests";
import { createSweepJob } from "../../api/backtests";
import { ApiClientError } from "../../api/client";
import { listStrategies } from "../../api/strategies";
import NewSweepJob from "./NewSweepJob";

vi.mock("../../api/backtests", async () => {
  const actual = await vi.importActual<typeof import("../../api/backtests")>(
    "../../api/backtests",
  );
  return {
    ...actual,
    createSweepJob: vi.fn(),
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
        <NewSweepJob />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("NewSweepJob", () => {
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
    vi.mocked(createSweepJob).mockResolvedValue({
      job_id: "job-sweep-1",
      ref_id: "sweep-1",
      status: "queued",
    } satisfies BacktestJobCreateResponse);
  });

  it("submits a typed sweep creation request with the expected body shape", async () => {
    const user = userEvent.setup();
    renderPage();

    // The form's default values already provide a valid search_spec JSON,
    // so we only need to fill in the user-supplied fields.
    await user.type(screen.getByLabelText(/Strategy Name/i), "MACross");
    await user.type(screen.getByLabelText(/Start Date/i), "2026-01-01");
    await user.type(screen.getByLabelText(/End Date/i), "2026-12-31");
    await user.click(screen.getByRole("button", { name: /Create Sweep/i }));

    await waitFor(() => expect(createSweepJob).toHaveBeenCalledTimes(1));
    const [body, idempotencyKey] = vi.mocked(createSweepJob).mock.calls[0] as [
      SweepRunRequest,
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
      search_type: "grid",
      select_metric: "sharpe_ratio",
      maximize: true,
      fail_fast: false,
      strategy_params: {},
    });
    expect(body.search_spec).toEqual({
      space: { fast: [5, 10], slow: [20, 60] },
      constraints: [],
    });
    // sweep_id is optional; it should be omitted from the body when
    // the user leaves the field empty (trim() → "").
    expect(body.sweep_id).toBeUndefined();
  });

  it("rejects submit with the Strategy name required error when the field is empty", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText(/Start Date/i), "2026-01-01");
    await user.type(screen.getByLabelText(/End Date/i), "2026-12-31");
    await user.click(screen.getByRole("button", { name: /Create Sweep/i }));

    expect(
      await screen.findByText(/Strategy name is required/i),
    ).toBeInTheDocument();
    expect(createSweepJob).not.toHaveBeenCalled();
  });

  it("rejects submit when end date is before start date", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText(/Strategy Name/i), "MACross");
    await user.type(screen.getByLabelText(/Start Date/i), "2026-06-30");
    await user.type(screen.getByLabelText(/End Date/i), "2026-01-01");
    await user.click(screen.getByRole("button", { name: /Create Sweep/i }));

    expect(
      await screen.findByText(/End date must be on or after start date/i),
    ).toBeInTheDocument();
    expect(createSweepJob).not.toHaveBeenCalled();
  });

  it("rejects submit when the search spec is missing the space object", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText(/Strategy Name/i), "MACross");
    // Use fireEvent.change for JSON-shaped input — `user.type` chokes
    // on `{`, `}`, `[`, `]`, `"` (treats them as keyboard chords).
    const searchSpecTextarea = screen.getByLabelText(/Search Spec JSON/i);
    fireEvent.change(searchSpecTextarea, {
      target: { value: JSON.stringify({ constraints: [] }) },
    });
    await user.type(screen.getByLabelText(/Start Date/i), "2026-01-01");
    await user.type(screen.getByLabelText(/End Date/i), "2026-12-31");
    await user.click(screen.getByRole("button", { name: /Create Sweep/i }));

    expect(
      await screen.findByText(/Search spec must include a JSON object field named space/i),
    ).toBeInTheDocument();
    expect(createSweepJob).not.toHaveBeenCalled();
  });

  it("rejects submit when the search spec space is empty", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText(/Strategy Name/i), "MACross");
    const searchSpecTextarea = screen.getByLabelText(/Search Spec JSON/i);
    fireEvent.change(searchSpecTextarea, {
      target: { value: JSON.stringify({ space: {}, constraints: [] }) },
    });
    await user.type(screen.getByLabelText(/Start Date/i), "2026-01-01");
    await user.type(screen.getByLabelText(/End Date/i), "2026-12-31");
    await user.click(screen.getByRole("button", { name: /Create Sweep/i }));

    expect(
      await screen.findByText(/Search spec space must contain at least one parameter/i),
    ).toBeInTheDocument();
    expect(createSweepJob).not.toHaveBeenCalled();
  });

  it("rejects submit when the search spec JSON is malformed", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText(/Strategy Name/i), "MACross");
    const searchSpecTextarea = screen.getByLabelText(/Search Spec JSON/i);
    fireEvent.change(searchSpecTextarea, { target: { value: "{not json" } });
    await user.type(screen.getByLabelText(/Start Date/i), "2026-01-01");
    await user.type(screen.getByLabelText(/End Date/i), "2026-12-31");
    await user.click(screen.getByRole("button", { name: /Create Sweep/i }));

    // `JSON.parse` throws a SyntaxError whose `.message` is something
    // like "Expected property name or '}' in JSON at position 1"; the
    // onSubmit catch propagates `err.message` directly. Match any
    // error-box text (i.e. anything in the error-box div) so this
    // assertion is robust across V8 message-format changes.
    const errorBox = await screen.findByText(/./, {
      selector: ".error-box",
    });
    expect(errorBox).toBeInTheDocument();
    expect(createSweepJob).not.toHaveBeenCalled();
  });

  it("includes sweep_id in the body when the user provides one", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText(/Strategy Name/i), "MACross");
    const sweepIdInput = screen.getByLabelText(/Sweep ID/i);
    fireEvent.change(sweepIdInput, { target: { value: "sweep-explicit-99" } });
    await user.type(screen.getByLabelText(/Start Date/i), "2026-01-01");
    await user.type(screen.getByLabelText(/End Date/i), "2026-12-31");
    await user.click(screen.getByRole("button", { name: /Create Sweep/i }));

    await waitFor(() => expect(createSweepJob).toHaveBeenCalledTimes(1));
    const [body] = vi.mocked(createSweepJob).mock.calls[0] as [
      SweepRunRequest,
      string,
    ];
    expect(body.sweep_id).toBe("sweep-explicit-99");
  });

  it("surfaces a server error in the inline error-box when createSweepJob rejects", async () => {
    const user = userEvent.setup();
    vi.mocked(createSweepJob).mockRejectedValueOnce(
      new ApiClientError(502, "upstream sweep service unavailable"),
    );
    renderPage();

    await user.type(screen.getByLabelText(/Strategy Name/i), "MACross");
    await user.type(screen.getByLabelText(/Start Date/i), "2026-01-01");
    await user.type(screen.getByLabelText(/End Date/i), "2026-12-31");
    await user.click(screen.getByRole("button", { name: /Create Sweep/i }));

    expect(
      await screen.findByText(/upstream sweep service unavailable/i),
    ).toBeInTheDocument();
  });
});
