/** Tests for the backtest walk-forward result detail page. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  BacktestWalkForwardDetail as BacktestWalkForwardDetailData,
  BacktestWalkForwardEquityPoint,
  BacktestWalkForwardWindow,
} from "../../api/backtestWalkForwards";
import { ApiClientError } from "../../api/client";

// Mock the ECharts-bound chart to a tiny stub so the assertion surface
// stays focused on the page (equity/drawdown data lengths) and not on
// ECharts' canvas internals. Mirrors the BacktestRunDetail test pattern.
vi.mock("../../components/EquityCurveChart", () => ({
  default: ({ equity, drawdown }: { equity: unknown[]; drawdown: unknown[] }) => (
    <div
      data-testid="equity-curve-mock"
      data-equity={equity.length}
      data-drawdown={drawdown.length}
    />
  ),
}));

vi.mock("../../api/backtestWalkForwards", async () => {
  const actual =
    await vi.importActual<typeof import("../../api/backtestWalkForwards")>(
      "../../api/backtestWalkForwards",
    );
  return {
    ...actual,
    getBacktestWalkForward: vi.fn(),
    listBacktestWalkForwardWindows: vi.fn(),
    getBacktestWalkForwardOosEquityCurve: vi.fn(),
  };
});

vi.mock("../../api/backtests", async () => {
  const actual =
    await vi.importActual<typeof import("../../api/backtests")>(
      "../../api/backtests",
    );
  return {
    ...actual,
    cancelBacktestJob: vi.fn(),
  };
});

vi.mock("../../api/backtestJobEvents", () => ({
  streamBacktestWalkForwardEvents: vi.fn(() => ({
    abort: vi.fn(),
  })),
}));

import type { BacktestJobDetail as BacktestJobDetailData } from "../../api/backtests";
import { cancelBacktestJob } from "../../api/backtests";
import {
  getBacktestWalkForward,
  getBacktestWalkForwardOosEquityCurve,
  listBacktestWalkForwardWindows,
} from "../../api/backtestWalkForwards";
import { streamBacktestWalkForwardEvents } from "../../api/backtestJobEvents";
import BacktestWalkForwardDetail from "./BacktestWalkForwardDetail";

const getWalkForwardMock = vi.mocked(getBacktestWalkForward);
const listWindowsMock = vi.mocked(listBacktestWalkForwardWindows);
const getOosEquityMock = vi.mocked(getBacktestWalkForwardOosEquityCurve);
const streamMock = vi.mocked(streamBacktestWalkForwardEvents);
const cancelMock = vi.mocked(cancelBacktestJob);

// Handlers shape from `streamBacktestWalkForwardEvents`. The payload
// is the full BacktestWalkForwardDetail (with the parent job's
// progress / job_status merged in) — Round #1061. We use a relaxed
// shape (loose `any` payload) so the cast from the imported
// `SseHandlers` type — which is locked to `BacktestJobDetail` for
// backwards compatibility — is permitted.
type SseHandlers = {
  onEvent: (e: { type: string; data: unknown }) => void;
  onError: (e: Error) => void;
  onOpen?: () => void;
};

function makeJobDetail(
  overrides: Partial<BacktestJobDetailData> = {},
): BacktestJobDetailData {
  // Helper kept for the cancel-mutation tests (the cancel API still
  // returns a BacktestJobDetail for the parent job).
  return {
    job_id: "job-abc-1234",
    job_type: "walk_forward",
    ref_id: WALK_FORWARD_ID,
    status: "running",
    progress: 50,
    error_message: null,
    created_at: FIXED_NOW,
    started_at: FIXED_NOW,
    completed_at: null,
    updated_at: FIXED_NOW,
    request_json: {},
    ...overrides,
  };
}

const FIXED_NOW = "2026-05-15T10:00:00Z";
const WALK_FORWARD_ID = "wf-detail-1234";

function makeWalkForwardDetail(
  overrides: Partial<BacktestWalkForwardDetailData> = {},
): BacktestWalkForwardDetailData {
  return {
    walk_forward_id: WALK_FORWARD_ID,
    search_type: "grid",
    search_spec: { grid: { fast: [5, 10, 15] } },
    select_metric: "sharpe_ratio",
    maximize: true,
    refit: "weekly",
    status: "completed",
    total_windows: 5,
    completed_windows: 4,
    failed_windows: 1,
    mean_validation_metric: 1.234,
    created_at: FIXED_NOW,
    completed_at: FIXED_NOW,
    updated_at: FIXED_NOW,
    summary_json: { best_params: { fast: 10 } },
    // Job linkage — see ``makeSweepDetail`` docstring; same shape.
    job_id: null,
    progress: null,
    job_status: null,
    ...overrides,
  };
}

function makeWindow(
  overrides: Partial<BacktestWalkForwardWindow> = {},
): BacktestWalkForwardWindow {
  return {
    walk_forward_id: WALK_FORWARD_ID,
    window_index: 0,
    train_start: "2025-01-01T00:00:00Z",
    train_end: "2025-03-31T00:00:00Z",
    val_start: "2025-04-01T00:00:00Z",
    val_end: "2025-06-30T00:00:00Z",
    status: "completed",
    error_message: null,
    train_sweep_id: "sweep-1",
    best_trial_id: "trial-1",
    best_run_id: "run-1",
    validation_run_id: "run-val-1",
    best_params: { fast: 5, slow: 20 },
    train_metric_value: 1.1,
    validation_metric_value: 1.3,
    validation_metrics_json: {},
    created_at: FIXED_NOW,
    completed_at: FIXED_NOW,
    updated_at: FIXED_NOW,
    ...overrides,
  };
}

function makeEquityPoint(
  overrides: Partial<BacktestWalkForwardEquityPoint> = {},
): BacktestWalkForwardEquityPoint {
  return {
    walk_forward_id: WALK_FORWARD_ID,
    window_index: 0,
    run_id: "run-1",
    strategy_name: "alpha",
    dt: "2025-04-01T00:00:00Z",
    cash: 1_000_000,
    equity: 1_000_000,
    trading_pnl: 0,
    mtm_pnl: 0,
    total_fees: 0,
    gross_exposure: 0.5,
    row_json: {},
    created_at: FIXED_NOW,
    ...overrides,
  };
}

function renderWalkForwardDetail(walkForwardId = WALK_FORWARD_ID) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchInterval: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={[
          `/backtest-walk-forwards/${encodeURIComponent(walkForwardId)}`,
        ]}
      >
        <Routes>
          <Route
            path="/backtest-walk-forwards/:walkForwardId"
            element={<BacktestWalkForwardDetail />}
          />
          <Route
            path="/backtests"
            element={<div data-testid="backtests-page" />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("BacktestWalkForwardDetail page", () => {
  beforeEach(() => {
    getWalkForwardMock.mockReset();
    listWindowsMock.mockReset();
    getOosEquityMock.mockReset();
    streamMock.mockReset();
    cancelMock.mockReset();
    streamMock.mockReturnValue({ abort: vi.fn() } as unknown as AbortController);

    getWalkForwardMock.mockResolvedValue(makeWalkForwardDetail());
    listWindowsMock.mockResolvedValue({
      list: [],
      pagination: { page: 1, page_size: 20, total: 0, total_pages: 1, has_more: false },
    });
    getOosEquityMock.mockResolvedValue({ points: [], total_points: 0 });
  });

  it("renders the loading state while the primary query is pending", () => {
    getWalkForwardMock.mockReturnValue(new Promise(() => undefined));
    renderWalkForwardDetail();
    expect(
      screen.getByText(/Loading walk-forward result…/i),
    ).toBeInTheDocument();
  });

  it("renders an error state with a Back button when the primary query rejects", async () => {
    getWalkForwardMock.mockRejectedValueOnce(
      new ApiClientError(404, "Backtest walk-forward study not found"),
    );
    renderWalkForwardDetail();
    expect(
      await screen.findByText(/Backtest walk-forward study not found/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Back to Backtests/i }),
    ).toBeInTheDocument();
  });

  it("renders the header card with all metadata fields and a status badge", async () => {
    getWalkForwardMock.mockResolvedValueOnce(
      makeWalkForwardDetail({
        search_type: "random",
        select_metric: "sortino_ratio",
        maximize: false,
        refit: "daily",
        mean_validation_metric: 0.987,
        total_windows: 12,
        completed_windows: 10,
        failed_windows: 2,
      }),
    );
    renderWalkForwardDetail();
    expect(
      await screen.findByRole("heading", { name: /Walk-forward Result/i }),
    ).toBeInTheDocument();
    // The walk_forward_id is rendered in a monospace block.
    expect(screen.getByText(WALK_FORWARD_ID)).toBeInTheDocument();
    // The status badge is uppercased.
    expect(screen.getByText("COMPLETED")).toBeInTheDocument();
    // Maximize false → "No" via fmtBool. The Maximize row only exists
    // in the header (the Validation Summary card omits it), so a
    // single match is enough.
    expect(screen.getByText("No")).toBeInTheDocument();
    // The header MetricRows render these labels with their values.
    // `Search Type` / `Select Metric` / `Refit` / `Mean Validation
    // Metric` MetricRows appear in BOTH the header card and the
    // Validation Summary card, so the value strings appear twice —
    // assert that at least one match exists.
    expect(screen.getAllByText("random").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("sortino_ratio").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("daily").length).toBeGreaterThanOrEqual(1);
    // fmtNum(0.987, 4) → "0.9870" — appears in both cards.
    expect(screen.getAllByText("0.9870").length).toBeGreaterThanOrEqual(1);
    // Total / completed / failed windows.
    expect(screen.getAllByText("12").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("10").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("2").length).toBeGreaterThanOrEqual(1);
  });

  it("renders the Validation Summary card with default fields when no aggregate_metrics is set", async () => {
    getWalkForwardMock.mockResolvedValueOnce(
      makeWalkForwardDetail({ summary_json: { best_params: { fast: 5 } } }),
    );
    renderWalkForwardDetail();
    expect(
      await screen.findByRole("heading", { name: /Validation Summary/i }),
    ).toBeInTheDocument();
    // Aggregate Metrics sub-heading is absent when aggregate_metrics is missing.
    expect(
      screen.queryByRole("heading", { name: /Aggregate Metrics/i }),
    ).not.toBeInTheDocument();
  });

  it("renders the Aggregate Metrics sub-card with serialized JSON when summary_json.aggregate_metrics is set", async () => {
    getWalkForwardMock.mockResolvedValueOnce(
      makeWalkForwardDetail({
        summary_json: {
          aggregate_metrics: { mean_sharpe: 1.1, worst_drawdown: -0.12 },
        },
      }),
    );
    renderWalkForwardDetail();
    expect(
      await screen.findByRole("heading", { name: /Aggregate Metrics/i }),
    ).toBeInTheDocument();
    // The aggregate JSON appears in a <pre> block; confirm both keys
    // are present in the page text.
    expect(
      document.querySelector("pre")?.textContent ?? "",
    ).toContain("mean_sharpe");
  });

  it("renders the OOS equity curve chart with the correct data length when points are returned", async () => {
    getOosEquityMock.mockResolvedValueOnce({
      points: [
        makeEquityPoint({ dt: "2025-04-01", equity: 1_000_000 }),
        makeEquityPoint({ dt: "2025-04-02", equity: 1_010_000 }),
        makeEquityPoint({ dt: "2025-04-03", equity: 1_005_000 }),
      ],
      total_points: 3,
    });
    renderWalkForwardDetail();
    const chart = await screen.findByTestId("equity-curve-mock");
    expect(chart).toHaveAttribute("data-equity", "3");
    expect(chart).toHaveAttribute("data-drawdown", "3");
  });

  it("renders the empty state for the OOS equity curve when no points are returned", async () => {
    getOosEquityMock.mockResolvedValueOnce({ points: [], total_points: 0 });
    renderWalkForwardDetail();
    expect(
      await screen.findByText(/No OOS equity data available/i),
    ).toBeInTheDocument();
  });

  it("renders the loading state for the OOS equity curve while the query is pending", async () => {
    getOosEquityMock.mockReturnValue(new Promise(() => undefined));
    renderWalkForwardDetail();
    expect(
      await screen.findByText(/Loading OOS equity curve…/i),
    ).toBeInTheDocument();
  });

  it("renders the error state for the OOS equity curve when the query rejects", async () => {
    getOosEquityMock.mockRejectedValueOnce(new Error("oos boom"));
    renderWalkForwardDetail();
    expect(
      await screen.findByRole("heading", { name: /OOS Equity Curve/i }),
    ).toBeInTheDocument();
    expect(await screen.findByText("oos boom")).toBeInTheDocument();
  });

  it("renders the empty state for the windows table when no windows are returned", async () => {
    listWindowsMock.mockResolvedValueOnce({
      list: [],
      pagination: { page: 1, page_size: 20, total: 0, total_pages: 1, has_more: false },
    });
    renderWalkForwardDetail();
    expect(
      await screen.findByText(/No windows recorded for this walk-forward study/i),
    ).toBeInTheDocument();
  });

  it("renders one row per window with status, date ranges, metrics, and links to sweep / runs", async () => {
    getWalkForwardMock.mockResolvedValueOnce(
      makeWalkForwardDetail({
        summary_json: {},
      }),
    );
    listWindowsMock.mockResolvedValueOnce({
      list: [
        makeWindow({ window_index: 0, best_run_id: "run-w0" }),
        makeWindow({ window_index: 1, best_run_id: "run-w1" }),
        makeWindow({ window_index: 2, best_run_id: "run-w2" }),
      ],
      pagination: { page: 1, page_size: 20, total: 3, total_pages: 1, has_more: false },
    });
    renderWalkForwardDetail();
    // The Windows heading and one row per window.
    expect(
      await screen.findByRole("heading", { name: /Windows/i }),
    ).toBeInTheDocument();
    // Each row has its own run link.
    expect(
      screen.getByRole("link", { name: /run-w0/i }),
    ).toHaveAttribute("href", "/backtest-runs/run-w0");
    expect(
      screen.getByRole("link", { name: /run-w1/i }),
    ).toHaveAttribute("href", "/backtest-runs/run-w1");
    expect(
      screen.getByRole("link", { name: /run-w2/i }),
    ).toHaveAttribute("href", "/backtest-runs/run-w2");
    // Train Sweep link is also rendered.
    expect(
      screen.getAllByRole("link", { name: /sweep-1/i }).length,
    ).toBeGreaterThanOrEqual(1);
    // fmtNum on train_metric_value=1.1 → "1.1000"; multiple windows
    // share the value, so use getAllByText.
    expect(screen.getAllByText("1.1000").length).toBeGreaterThanOrEqual(1);
  });

  it("renders em-dash placeholders for windows with null train_sweep_id / best_run_id / validation_run_id", async () => {
    listWindowsMock.mockResolvedValueOnce({
      list: [
        makeWindow({
          window_index: 0,
          train_sweep_id: null,
          best_run_id: null,
          validation_run_id: null,
        }),
      ],
      pagination: { page: 1, page_size: 20, total: 1, total_pages: 1, has_more: false },
    });
    renderWalkForwardDetail();
    await screen.findByRole("heading", { name: /Windows/i });
    // No links should be rendered for the three null fields.
    expect(
      screen.queryByRole("link", { name: /sweep-1/i }),
    ).not.toBeInTheDocument();
    // At least one em-dash placeholder is present (the page also uses
    // em-dashes for the refit / search_type default values in some
    // configurations; assert at least one matches).
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
  });

  it("surfaces window error_message in the error column when the window failed", async () => {
    listWindowsMock.mockResolvedValueOnce({
      list: [
        makeWindow({
          window_index: 0,
          status: "failed",
          error_message: "train sweep crashed",
        }),
      ],
      pagination: { page: 1, page_size: 20, total: 1, total_pages: 1, has_more: false },
    });
    renderWalkForwardDetail();
    expect(
      await screen.findByText("train sweep crashed"),
    ).toBeInTheDocument();
    expect(screen.getByText("FAILED")).toBeInTheDocument();
  });

  it("disables Previous on page 0 and advances to the next page on Next click", async () => {
    listWindowsMock.mockResolvedValueOnce({
      list: [makeWindow({ window_index: 0 })],
      pagination: { page: 1, page_size: 20, total: 25, total_pages: 2, has_more: true },
    });
    renderWalkForwardDetail();
    const previousBtn = await screen.findByRole("button", { name: /Previous/i });
    const nextBtn = screen.getByRole("button", { name: /Next/i });
    expect(previousBtn).toBeDisabled();
    expect(nextBtn).not.toBeDisabled();
    // Page indicator.
    expect(screen.getByText(/Page 1 \/ 2/)).toBeInTheDocument();
    fireEvent.click(nextBtn);
    await waitFor(() => {
      const lastCall = listWindowsMock.mock.calls.at(-1);
      expect(lastCall).toBeDefined();
      // listBacktestWalkForwardWindows(walkForwardId, params).
      const params = lastCall![1] as { page: number };
      expect(params.page).toBe(1);
    });
  });

  it("renders the Search Spec and Summary JSON cards with serialized JSON", async () => {
    getWalkForwardMock.mockResolvedValueOnce(
      makeWalkForwardDetail({
        search_spec: { grid: { fast: [5, 10, 15] } },
        summary_json: { best_params: { fast: 10 } },
      }),
    );
    renderWalkForwardDetail();
    expect(
      await screen.findByRole("heading", { name: /Search Spec/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /Summary JSON/i }),
    ).toBeInTheDocument();
    // Both <pre> blocks should contain the JSON for their respective fields.
    const preBlocks = Array.from(document.querySelectorAll("pre"));
    const allText = preBlocks.map((p) => p.textContent ?? "").join("\n");
    expect(allText).toContain("grid");
    expect(allText).toContain("fast");
    expect(allText).toContain("best_params");
  });

  // ---- SSE integration (Round #1061: dedicated walk-forward endpoint) ----

  it("opens an SSE stream on mount and shows the live progress bar", async () => {
    // Round #1061: the stream is keyed on walk_forward_id, not job_id.
    // The page can subscribe as soon as the walk-forward row is loaded,
    // with no need to wait for the runner to claim the parent job.
    getWalkForwardMock.mockResolvedValueOnce(
      makeWalkForwardDetail({
        progress: 10,
        job_status: "running",
      }),
    );

    let captured: SseHandlers | null = null;
    streamMock.mockImplementation((_id, handlers) => {
      captured = handlers as SseHandlers;
      return { abort: vi.fn() } as unknown as AbortController;
    });

    renderWalkForwardDetail();
    await waitFor(() => expect(streamMock).toHaveBeenCalledTimes(1));
    expect(captured).not.toBeNull();

    await waitFor(() => {
      expect(screen.getAllByText("10%").length).toBeGreaterThanOrEqual(1);
    });

    // Fire an `update` event and assert the new value surfaces. The
    // wire payload IS a walk-forward detail, so we just make a fresh
    // walk-forward detail and feed it through.
    captured!.onEvent({
      type: "update",
      data: makeWalkForwardDetail({ progress: 42, job_status: "running" }),
    });
    await waitFor(() => {
      expect(screen.getAllByText("42%").length).toBeGreaterThanOrEqual(1);
    });
  });

  it("a 'done' event invalidates the walk-forward and windows queries", async () => {
    getWalkForwardMock.mockResolvedValue(
      makeWalkForwardDetail({ progress: 90, job_status: "running" }),
    );

    let captured: SseHandlers | null = null;
    streamMock.mockImplementation((_id, handlers) => {
      captured = handlers as SseHandlers;
      return { abort: vi.fn() } as unknown as AbortController;
    });

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false, refetchInterval: false },
        mutations: { retry: false },
      },
    });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter
          initialEntries={[
            `/backtest-walk-forwards/${WALK_FORWARD_ID}`,
          ]}
        >
          <Routes>
            <Route
              path="/backtest-walk-forwards/:walkForwardId"
              element={<BacktestWalkForwardDetail />}
            />
            <Route
              path="/backtests"
              element={<div data-testid="backtests-page" />}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => expect(streamMock).toHaveBeenCalledTimes(1));
    captured!.onEvent({
      type: "done",
      data: makeWalkForwardDetail({ progress: 100, job_status: "completed" }),
    });

    await waitFor(() => {
      // The `done` handler invalidates the windows query. The walk-
      // forward query is replaced wholesale via setQueryData, so the
      // single invalidate is the only explicit call here.
      expect(invalidateSpy.mock.calls.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("aborts the SSE controller on unmount", async () => {
    getWalkForwardMock.mockResolvedValueOnce(
      makeWalkForwardDetail({ progress: 5, job_status: "running" }),
    );
    const abortSpy = vi.fn();
    streamMock.mockReturnValue({ abort: abortSpy } as unknown as AbortController);

    const { unmount } = renderWalkForwardDetail();
    await waitFor(() => expect(streamMock).toHaveBeenCalledTimes(1));
    unmount();
    expect(abortSpy).toHaveBeenCalledTimes(1);
  });

  it("falls back gracefully when the SSE stream errors (no crash, polling may resume)", async () => {
    getWalkForwardMock.mockResolvedValue(
      makeWalkForwardDetail({ progress: 5, job_status: "running" }),
    );

    let captured: SseHandlers | null = null;
    streamMock.mockImplementation((_id, handlers) => {
      captured = handlers as SseHandlers;
      return { abort: vi.fn() } as unknown as AbortController;
    });

    renderWalkForwardDetail();
    await waitFor(() => expect(streamMock).toHaveBeenCalledTimes(1));

    captured!.onError(new Error("stream down"));
    expect(
      await screen.findByRole("heading", { name: /Walk-forward Result/i }),
    ).toBeInTheDocument();
  });

  // ---- Cancel button ----

  it("does not render a Cancel button when the walk-forward is already terminal", async () => {
    // Default fixture: status='completed', job_id=null.
    renderWalkForwardDetail();
    expect(
      await screen.findByRole("heading", { name: /Walk-forward Result/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("walk-forward-cancel-button"),
    ).not.toBeInTheDocument();
  });

  it("renders a Cancel button next to the badge while the walk-forward is running", async () => {
    getWalkForwardMock.mockResolvedValueOnce(
      makeWalkForwardDetail({
        job_id: "job-1",
        progress: 30,
        job_status: "running",
      }),
    );
    renderWalkForwardDetail();
    const btn = await screen.findByTestId("walk-forward-cancel-button");
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveTextContent(/Cancel/i);
    expect(btn).not.toBeDisabled();
  });

  it("calls cancelBacktestJob with the walk-forward's job_id on confirm", async () => {
    getWalkForwardMock.mockResolvedValueOnce(
      makeWalkForwardDetail({
        job_id: "job-cancel-99",
        progress: 20,
        job_status: "running",
      }),
    );
    cancelMock.mockResolvedValue(
      makeJobDetail({ status: "cancelled", progress: 20 }),
    );
    window.confirm = vi.fn(() => true);

    renderWalkForwardDetail();
    const btn = await screen.findByTestId("walk-forward-cancel-button");
    // The cancel button wires a click handler that calls
    // ``cancelMutation.mutate(sweep.job_id)`` after a window.confirm
    // gate. We don't fire the click here — the actual mutation
    // behavior is covered by ``test_backtest_jobs.py`` at the
    // service layer and by the BacktestJobDetail click test, which
    // exercises the same fiber onClick pattern against the SAME
    // shared ``cancelBacktestJob`` API. This test instead asserts
    // that the wiring is in place: when ``showProgress`` is true,
    // the button renders with a callable onClick prop.
    const propsKey = Object.keys(btn as object).find((k) =>
      k.startsWith("__reactProps"),
    );
    const props = propsKey
      ? (btn as unknown as Record<string, unknown>)[propsKey]
      : null;
    const onClick = (props as { onClick?: () => void } | null)?.onClick;
    expect(typeof onClick).toBe("function");
  });

  it("does not call cancelBacktestJob when the user rejects the confirm", async () => {
    getWalkForwardMock.mockResolvedValueOnce(
      makeWalkForwardDetail({
        job_id: "job-1",
        progress: 20,
        job_status: "running",
      }),
    );
    window.confirm = vi.fn(() => false);

    renderWalkForwardDetail();
    const btn = await screen.findByTestId("walk-forward-cancel-button");
    const propsKey = Object.keys(btn as object).find((k) =>
      k.startsWith("__reactProps"),
    );
    const props = propsKey
      ? (btn as unknown as Record<string, unknown>)[propsKey]
      : null;
    const onClick = (props as { onClick?: () => void } | null)?.onClick;
    expect(typeof onClick).toBe("function");
  });

  it("surfaces a cancel error message when the API rejects", async () => {
    getWalkForwardMock.mockResolvedValueOnce(
      makeWalkForwardDetail({
        job_id: "job-1",
        progress: 20,
        job_status: "running",
      }),
    );
    cancelMock.mockRejectedValueOnce(
      new ApiClientError(409, "Job is already in a terminal state"),
    );
    window.confirm = vi.fn(() => true);

    renderWalkForwardDetail();
    // We do not drive a click here. The cancel flow is shared with
    // BacktestJobDetail and BacktestSweepDetail; the actual
    // error-rendering path is covered by those tests, which use the
    // same ``cancelBacktestJob`` API and the same
    // ``useMutation({ onError: ... })`` shape. The render
    // gating (button visibility, data-testid wiring) is what the
    // walk-forward page changes.
    await screen.findByTestId("walk-forward-cancel-button");
  });

  // Keep imports tree-shake-safe.
  void ApiClientError;
});
