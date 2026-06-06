/** Tests for the StrategyEdit page. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { StrategyDetail } from "../api/strategies";
import type { ApiResponse } from "../api/client";

vi.mock("../api/strategies", async () => {
  const actual = await vi.importActual<typeof import("../api/strategies")>(
    "../api/strategies",
  );
  return {
    ...actual,
    getStrategyDetail: vi.fn(),
    updateStrategy: vi.fn(),
  };
});

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    apiFetch: vi.fn(),
  };
});

import { getStrategyDetail, updateStrategy } from "../api/strategies";
import { apiFetch } from "../api/client";
import StrategyEdit from "./StrategyEdit";

const getMock = vi.mocked(getStrategyDetail);
const updateMock = vi.mocked(updateStrategy);
const apiFetchMock = vi.mocked(apiFetch);

const STRATEGY_CODE = "STR_FUT_001";
const FIXED_NOW = "2026-05-15T10:00:00Z";

function makeDetail(overrides: Partial<StrategyDetail> = {}): StrategyDetail {
  return {
    id: "str-1",
    name: "My Strategy",
    description: "A description",
    detail_html: "<p>Hello</p>",
    category: { id: "cat-1", name: "Futures" },
    asset_class: "future",
    market: "CN",
    risk_level: "medium",
    status: "active",
    tags: [],
    creator: { id: "u-1", name: "Alice", avatar: "", bio: "" },
    performance: {},
    backtest_period: { start: "2024-01-01", end: "2024-12-31" },
    subscriber_count: 0,
    is_subscribed: false,
    subscription_info: null,
    subscription_price: { monthly: 99, yearly: 999 },
    published_at: FIXED_NOW,
    updated_at: FIXED_NOW,
    ...overrides,
  };
}

function wrapDetail(d: StrategyDetail): ApiResponse<StrategyDetail> {
  return { code: 0, message: "ok", data: d, timestamp: 0, request_id: "test" };
}

function renderEdit(code = STRATEGY_CODE) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/strategies/${code}/edit`]}>
        <Routes>
          <Route path="/strategies/:code/edit" element={<StrategyEdit />} />
          <Route path="/strategies" element={<div data-testid="strategies-page" />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  getMock.mockReset();
  updateMock.mockReset();
  apiFetchMock.mockReset();
  // Default category list.
  apiFetchMock.mockResolvedValue({
    code: 0,
    message: "ok",
    data: { categories: [{ id: "cat-1", name: "Futures" }, { id: "cat-2", name: "Equities" }] },
    timestamp: 0,
    request_id: "test",
  });
  getMock.mockResolvedValue(wrapDetail(makeDetail()));
  updateMock.mockResolvedValue({
    code: 0,
    message: "ok",
    data: makeDetail(),
    timestamp: 0,
    request_id: "test",
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("StrategyEdit — render", () => {
  it("renders the loading state while the detail query is pending", () => {
    getMock.mockReturnValue(new Promise(() => undefined));
    renderEdit();
    expect(screen.getByText(/Loading strategy…/i)).toBeInTheDocument();
  });

  it("pre-populates the form fields from the strategy detail", async () => {
    renderEdit();
    await waitFor(() => {
      expect(screen.getByDisplayValue("My Strategy")).toBeInTheDocument();
    });
    expect(screen.getByDisplayValue("A description")).toBeInTheDocument();
    expect(screen.getByDisplayValue("<p>Hello</p>")).toBeInTheDocument();
    // subscription_monthly is a numeric input with valueAsNumber.
    const monthly = screen.getByLabelText(/Monthly Price/i) as HTMLInputElement;
    expect(monthly.value).toBe("99");
  });

  it("shows the categories in the dropdown", async () => {
    renderEdit();
    await waitFor(() => {
      expect(screen.getByRole("option", { name: /Futures/ })).toBeInTheDocument();
    });
    expect(screen.getByRole("option", { name: /Equities/ })).toBeInTheDocument();
  });

  it("renders an error state with a Back button when the detail query fails", async () => {
    getMock.mockRejectedValueOnce(new Error("Network error"));
    renderEdit();
    await waitFor(() => {
      expect(screen.getByText(/Network error/i)).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /Back to Strategies/i })).toBeInTheDocument();
  });
});

describe("StrategyEdit — submit", () => {
  it("calls updateStrategy with the edited name on save", async () => {
    const user = userEvent.setup();
    renderEdit();
    await waitFor(() => {
      expect(screen.getByDisplayValue("My Strategy")).toBeInTheDocument();
    });
    const nameInput = screen.getByLabelText(/^Name/i) as HTMLInputElement;
    await user.clear(nameInput);
    await user.type(nameInput, "Renamed Strategy");
    await user.click(screen.getByRole("button", { name: /Save Changes/i }));
    await waitFor(() => {
      expect(updateMock).toHaveBeenCalledTimes(1);
    });
    const body = updateMock.mock.calls[0][1] as { name: string };
    expect(body.name).toBe("Renamed Strategy");
  });

  it("shows the 'updated successfully' banner after a successful save", async () => {
    const user = userEvent.setup();
    renderEdit();
    await waitFor(() => {
      expect(screen.getByDisplayValue("My Strategy")).toBeInTheDocument();
    });
    const nameInput = screen.getByLabelText(/^Name/i) as HTMLInputElement;
    await user.clear(nameInput);
    await user.type(nameInput, "Renamed");
    await user.click(screen.getByRole("button", { name: /Save Changes/i }));
    await waitFor(() => {
      expect(screen.getByText(/updated successfully/i)).toBeInTheDocument();
    });
  });
});
