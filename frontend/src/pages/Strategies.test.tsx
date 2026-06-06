/** Tests for the Strategies list page. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { StrategySummary } from "../api/strategies";

vi.mock("../api/strategies", async () => {
  const actual = await vi.importActual<typeof import("../api/strategies")>(
    "../api/strategies",
  );
  return {
    ...actual,
    listStrategies: vi.fn(),
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

import { listStrategies } from "../api/strategies";
import { subscribe, unsubscribe } from "../api/subscriptions";
import Strategies from "./Strategies";

const listMock = vi.mocked(listStrategies);
const subscribeMock = vi.mocked(subscribe);
const unsubscribeMock = vi.mocked(unsubscribe);

function makeStrategy(overrides: Partial<StrategySummary> = {}): StrategySummary {
  return {
    id: "strat-1",
    name: "MA Cross",
    code: "MACross",
    subscriber_count: 12,
    is_subscribed: false,
    subscription_price: { monthly: 99, yearly: 999 },
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <Strategies />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  listMock.mockReset();
  subscribeMock.mockReset();
  unsubscribeMock.mockReset();
  subscribeMock.mockResolvedValue(undefined as never);
  unsubscribeMock.mockResolvedValue(undefined as never);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Strategies — render", () => {
  it("renders the loading state while the query is pending", () => {
    listMock.mockReturnValue(new Promise(() => undefined));
    renderPage();
    expect(screen.getByText(/loading…/i)).toBeInTheDocument();
  });

  it("shows the empty state when the strategy list is empty", async () => {
    listMock.mockResolvedValue([]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/no strategies found/i)).toBeInTheDocument();
    });
  });

  it("renders one row per strategy with a Subscribe button for unsubscribed rows", async () => {
    listMock.mockResolvedValue([
      makeStrategy({ id: "s-1", name: "Alpha" }),
      makeStrategy({ id: "s-2", name: "Beta", is_subscribed: true }),
    ]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Alpha")).toBeInTheDocument();
    });
    expect(screen.getByText("Beta")).toBeInTheDocument();
    // One row is subscribed → exactly one "Unsubscribe" button.
    expect(screen.getByRole("button", { name: "Unsubscribe" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Subscribe" })).toBeInTheDocument();
  });

  it("shows a free-tier label when both prices are zero", async () => {
    listMock.mockResolvedValue([
      makeStrategy({ id: "s-1", name: "Freebie", subscription_price: { monthly: 0, yearly: 0 } }),
    ]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Free")).toBeInTheDocument();
    });
  });
});

describe("Strategies — subscribe flow", () => {
  it("opens the plan picker when Subscribe is clicked, then calls subscribe() with monthly plan", async () => {
    listMock.mockResolvedValue([makeStrategy()]);
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Subscribe/i })).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: /Subscribe/i }));
    // Plan picker shows Monthly / Yearly options.
    await waitFor(() => {
      expect(screen.getByRole("option", { name: /Monthly/i })).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: /^OK$/i }));
    await waitFor(() => {
      expect(subscribeMock).toHaveBeenCalledWith(
        "strat-1",
        expect.objectContaining({ plan_type: "monthly" }),
      );
    });
  });
});

describe("Strategies — unsubscribe flow", () => {
  it("calls unsubscribe() when Unsubscribe is clicked on a subscribed row", async () => {
    listMock.mockResolvedValue([makeStrategy({ is_subscribed: true })]);
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Unsubscribe/i })).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: /Unsubscribe/i }));
    await waitFor(() => {
      expect(unsubscribeMock).toHaveBeenCalledWith("strat-1");
    });
  });
});

describe("Strategies — error", () => {
  it("surfaces an error message when the list query rejects", async () => {
    listMock.mockRejectedValue(new Error("Boom"));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/boom/i)).toBeInTheDocument();
    });
  });
});
