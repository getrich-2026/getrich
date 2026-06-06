/** Tests for the strategy detail page. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { StrategyDetail } from "../api/strategies";
import { ApiClientError } from "../api/client";

vi.mock("../api/strategies", async () => {
  const actual = await vi.importActual<typeof import("../api/strategies")>(
    "../api/strategies",
  );
  return {
    ...actual,
    getStrategyDetail: vi.fn(),
  };
});

vi.mock("../api/subscriptions", async () => {
  const actual = await vi.importActual<typeof import("../api/subscriptions")>(
    "../api/subscriptions",
  );
  return {
    ...actual,
    subscribe: vi.fn(),
    unsubscribe: vi.fn(),
  };
});

import { getStrategyDetail } from "../api/strategies";
import { subscribe, unsubscribe } from "../api/subscriptions";
import StrategyDetailPage from "./StrategyDetail";

const getMock = vi.mocked(getStrategyDetail);
const subscribeMock = vi.mocked(subscribe);
const unsubscribeMock = vi.mocked(unsubscribe);

const FIXED_NOW = "2026-05-15T10:00:00Z";
const STRATEGY_CODE = "STR_FUT_001";

function makeStrategy(
  overrides: Partial<StrategyDetail> = {},
): StrategyDetail {
  return {
    id: "str-1",
    name: "Demo Strategy",
    description: "A short description.",
    detail_html: "<h2>Hello</h2><p>Some safe body content.</p>",
    category: { id: "cat-1", name: "Futures" },
    asset_class: "future",
    market: "CN",
    risk_level: "medium",
    status: "published",
    tags: ["momentum"],
    creator: {
      id: "u-1",
      name: "Alice",
      avatar: "",
      bio: "Quant author",
    },
    performance: { sharpe_ratio: 1.5, max_drawdown: -0.12 },
    backtest_period: { start: "2024-01-01", end: "2025-12-31" },
    subscriber_count: 42,
    is_subscribed: false,
    subscription_info: null,
    subscription_price: { monthly: 99, yearly: 999 },
    published_at: FIXED_NOW,
    updated_at: FIXED_NOW,
    ...overrides,
  };
}

// `getStrategyDetail` returns `Promise<ApiResponse<StrategyDetail>>` — the
// page does `res.data` to unwrap. The mock has to mirror that envelope
// shape or `strategy` ends up undefined and the page falls into the
// error state.
function wrapStrategy(s: StrategyDetail) {
  return {
    code: 0,
    message: "ok",
    data: s,
    timestamp: 0,
    request_id: "test",
  };
}

function renderDetail(strategyCode = STRATEGY_CODE) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchInterval: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/strategies/${strategyCode}`]}>
        <Routes>
          <Route
            path="/strategies/:code"
            element={<StrategyDetailPage />}
          />
          <Route
            path="/strategies"
            element={<div data-testid="strategies-page" />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("StrategyDetail page", () => {
  beforeEach(() => {
    getMock.mockReset();
    subscribeMock.mockReset();
    unsubscribeMock.mockReset();
    getMock.mockResolvedValue(wrapStrategy(makeStrategy()));
    // `subscribe` / `unsubscribe` mocks only need to *resolve* — the
    // mutate hooks are not exercised by the three tests in this file
    // (the loading/error/sanitize paths never call them). The shape
    // of the resolved value is irrelevant; we just need `.resolves`.
    subscribeMock.mockResolvedValue(undefined as never);
    unsubscribeMock.mockResolvedValue(undefined as never);
  });

  it("renders the loading state while the primary query is pending", () => {
    getMock.mockReturnValue(new Promise(() => undefined));
    renderDetail();
    expect(screen.getByText(/Loading strategy…/i)).toBeInTheDocument();
  });

  it("renders an error state with a Back button when the query rejects", async () => {
    getMock.mockRejectedValueOnce(
      new ApiClientError(404, "Strategy not found"),
    );
    renderDetail();
    // The error message (the ApiClientError's "API {status}: {detail}"
    // string contains "Strategy not found" as a substring).
    expect(await screen.findByText(/Strategy not found/i)).toBeInTheDocument();
    // The Back control is a <button> (uses navigate(-1)), not a link.
    expect(
      screen.getByRole("button", { name: /Back/i }),
    ).toBeInTheDocument();
  });

  it("sanitizes the detail_html: strips <script>, removes onerror, preserves safe tags", async () => {
    getMock.mockResolvedValueOnce(
      wrapStrategy(
        makeStrategy({
          detail_html:
            '<img src="x" onerror="window.__xss=true">' +
            "<script>alert(1)</script>" +
            "<h2>Safe Heading</h2>" +
            '<a href="javascript:alert(1)">click</a>' +
            "<p>body</p>",
        }),
      ),
    );
    renderDetail();
    // The safe heading and body are rendered.
    await waitFor(() => {
      expect(screen.getByText("Safe Heading")).toBeInTheDocument();
    });
    // The detail-html div exists.
    const detailEl = document.querySelector(".detail-html");
    expect(detailEl).toBeTruthy();
    const inner = detailEl?.innerHTML ?? "";
    // <script> tag is gone (no inline script execution).
    expect(inner).not.toMatch(/<script/i);
    // onerror is gone (no event-handler execution).
    expect(inner).not.toMatch(/onerror/i);
    // javascript: URI is stripped from the href.
    expect(inner.toLowerCase()).not.toContain("javascript:");
    // window.__xss was never set — the JS payload never executed.
    expect((window as unknown as { __xss?: boolean }).__xss).toBeUndefined();
  });
});
