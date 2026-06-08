/** Tests for the SignalDetail page. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SignalDetail } from "../api/signals";
import type { ApiResponse } from "../api/client";

vi.mock("../api/signals", async () => {
  const actual = await vi.importActual<typeof import("../api/signals")>("../api/signals");
  return {
    ...actual,
    getSignalDetail: vi.fn(),
    markSignalRead: vi.fn(),
    executeSignal: vi.fn(),
  };
});

import { executeSignal, getSignalDetail, markSignalRead } from "../api/signals";
import SignalDetailPage from "./SignalDetail";

const getMock = vi.mocked(getSignalDetail);
const readMock = vi.mocked(markSignalRead);
const executeMock = vi.mocked(executeSignal);

const SIGNAL_CODE = "sig-1";
const FIXED = "2026-05-15T10:00:00Z";

function makeSignal(overrides: Partial<SignalDetail> = {}): SignalDetail {
  return {
    id: SIGNAL_CODE,
    strategy: { id: "s-1", name: "MA Cross", category: "trend", risk_level: "medium" },
    symbol: "000001.SZ",
    symbol_name: "Ping An Bank",
    signal_type: "entry",
    action: "buy",
    direction: "long",
    exchange: "SZSE",
    trigger_price: 10.5,
    target_price: 11,
    stop_loss_price: 10,
    suggested_quantity: 100,
    confidence: 0.8,
    urgency: "high",
    position_pct: 0.1,
    reason: "MACD bullish crossover",
    reason_detail: null,
    market_snapshot: null,
    historical_performance: null,
    user_state: { is_read: false, is_executed: false, read_at: null, executed_price: null, note: null },
    status: "active",
    trigger_time: FIXED,
    expired_at: null,
    ...overrides,
  };
}

function wrap(s: SignalDetail): ApiResponse<SignalDetail> {
  return { code: 0, message: "ok", data: s, timestamp: 0, request_id: "test" };
}

function renderDetail(code = SIGNAL_CODE) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/signals/${code}`]}>
        <Routes>
          <Route path="/signals/:code" element={<SignalDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  getMock.mockReset();
  readMock.mockReset();
  executeMock.mockReset();
  getMock.mockResolvedValue(wrap(makeSignal()));
  readMock.mockResolvedValue({
    code: 0,
    message: "ok",
    data: { signal_id: SIGNAL_CODE, is_read: true, read_at: FIXED, remaining_unread: 0 },
    timestamp: 0,
    request_id: "test",
  });
  executeMock.mockResolvedValue({
    code: 0,
    message: "ok",
    data: { signal_id: SIGNAL_CODE, is_executed: true, executed_price: 10.5, executed_at: FIXED, slippage: 0, slippage_pct: 0 },
    timestamp: 0,
    request_id: "test",
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SignalDetail — render", () => {
  it("renders the loading state while the detail query is pending", () => {
    getMock.mockReturnValue(new Promise(() => undefined));
    renderDetail();
    expect(screen.getByText(/Loading signal…/i)).toBeInTheDocument();
  });

  it("renders the strategy name, symbol, and price targets", async () => {
    renderDetail();
    await waitFor(() => {
      expect(screen.getByText("MA Cross")).toBeInTheDocument();
    });
    expect(screen.getByText(/Ping An Bank/)).toBeInTheDocument();
    expect(screen.getByText("10.5000")).toBeInTheDocument();
    expect(screen.getByText("11.0000")).toBeInTheDocument();
  });

  it("renders the reason text", async () => {
    renderDetail();
    await waitFor(() => {
      expect(screen.getByText("MACD bullish crossover")).toBeInTheDocument();
    });
  });

  it("renders an error state with a Back button when the query rejects", async () => {
    getMock.mockRejectedValueOnce(new Error("Boom"));
    renderDetail();
    await waitFor(() => {
      expect(screen.getByText(/Boom/i)).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /^Back$/i })).toBeInTheDocument();
  });

  it("auto-marks the signal as read on first view when is_read=false", async () => {
    renderDetail();
    await waitFor(() => {
      expect(readMock).toHaveBeenCalledWith(SIGNAL_CODE);
    });
  });
});

describe("SignalDetail — execute form", () => {
  it("calls executeSignal with the entered price and quantity", async () => {
    const user = userEvent.setup();
    renderDetail();
    await waitFor(() => {
      expect(screen.getByText("MA Cross")).toBeInTheDocument();
    });
    const price = screen.getByLabelText(/Executed Price/i) as HTMLInputElement;
    await user.clear(price);
    await user.type(price, "11.25");
    const qty = screen.getByLabelText(/Quantity/i) as HTMLInputElement;
    await user.clear(qty);
    await user.type(qty, "50");
    await user.click(screen.getByRole("button", { name: /Record Execution/i }));
    await waitFor(() => {
      expect(executeMock).toHaveBeenCalledTimes(1);
    });
    const body = executeMock.mock.calls[0][1] as { executed_price: number; executed_quantity: number };
    expect(body.executed_price).toBe(11.25);
    expect(body.executed_quantity).toBe(50);
  });

  it("hides the execute form for an expired signal", async () => {
    getMock.mockResolvedValueOnce(
      wrap(makeSignal({ status: "expired" })),
    );
    renderDetail();
    await waitFor(() => {
      expect(screen.getByText(/expired or cancelled/i)).toBeInTheDocument();
    });
  });
});
