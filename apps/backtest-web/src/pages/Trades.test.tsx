/** Tests for the Trades page. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { StrategySummary, TradeRecord } from "../api/strategies";
import type { PaginatedResponse } from "../api/client";

vi.mock("../api/strategies", async () => {
  const actual = await vi.importActual<typeof import("../api/strategies")>(
    "../api/strategies",
  );
  return {
    ...actual,
    listStrategies: vi.fn(),
    listTrades: vi.fn(),
  };
});

import { listStrategies, listTrades } from "../api/strategies";
import Trades from "./Trades";

const listStratMock = vi.mocked(listStrategies);
const listTradesMock = vi.mocked(listTrades);

const STRATEGIES: StrategySummary[] = [
  {
    id: "s-1",
    name: "Alpha",
    code: "ALPHA",
    subscriber_count: 0,
    is_subscribed: false,
    subscription_price: { monthly: 0, yearly: 0 },
  },
];

const TRADE: TradeRecord = {
  id: "t-1",
  strategy_id: "s-1",
  signal_id: "sig-1",
  symbol: "000001.SZ",
  action: "buy",
  quantity: 100,
  price: 10.5,
  notional: 1050,
  fee: 1.05,
  avg_cost: 10.5,
  realized_pnl: 0,
  cumulative_pnl: null,
  executed_at: "2024-06-01T10:00:00+08:00",
  bar_dt: null,
  tag: null,
};

function wrapTrades(items: TradeRecord[], total = items.length): PaginatedResponse<TradeRecord> {
  return {
    data: items,
    total,
    limit: 20,
    offset: 0,
  };
}

function renderPage(initial = "/trades") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <QueryClientProvider client={queryClient}>
        <Trades />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  listStratMock.mockReset();
  listTradesMock.mockReset();
  listStratMock.mockResolvedValue(STRATEGIES);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Trades — render", () => {
  it("shows a 'select a strategy' hint when no strategy is chosen", async () => {
    listTradesMock.mockResolvedValue(wrapTrades([]));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/select a strategy to view its trades/i)).toBeInTheDocument();
    });
    expect(listTradesMock).not.toHaveBeenCalled();
  });

  it("auto-selects the strategy from the ?strategy= query string", async () => {
    listTradesMock.mockResolvedValue(wrapTrades([TRADE]));
    renderPage("/trades?strategy=s-1");
    await waitFor(() => {
      expect(listTradesMock).toHaveBeenCalledWith(
        "s-1",
        expect.objectContaining({ limit: 20, offset: 0 }),
      );
    });
  });

  it("renders one row per trade with symbol, action, qty, price", async () => {
    listTradesMock.mockResolvedValue(wrapTrades([TRADE]));
    renderPage("/trades?strategy=s-1");
    await waitFor(() => {
      expect(screen.getByText("000001.SZ")).toBeInTheDocument();
    });
    expect(screen.getByText("buy")).toBeInTheDocument();
    expect(screen.getByText("100")).toBeInTheDocument();
    expect(screen.getByText("10.5")).toBeInTheDocument();
  });

  it("shows an empty-state row when the strategy has no trades", async () => {
    listTradesMock.mockResolvedValue(wrapTrades([]));
    renderPage("/trades?strategy=s-1");
    await waitFor(() => {
      expect(screen.getByText(/no trades found/i)).toBeInTheDocument();
    });
  });

  it("changes the strategy when the picker changes", async () => {
    listTradesMock.mockResolvedValue(wrapTrades([]));
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("option", { name: /Alpha/i })).toBeInTheDocument();
    });
    await user.selectOptions(screen.getByLabelText(/Strategy:/i), "s-1");
    await waitFor(() => {
      expect(listTradesMock).toHaveBeenCalledWith("s-1", expect.anything());
    });
  });
});

describe("Trades — error", () => {
  it("surfaces an error message when the trades query rejects", async () => {
    listTradesMock.mockRejectedValue(new Error("Network down"));
    renderPage("/trades?strategy=s-1");
    await waitFor(() => {
      expect(screen.getByText(/network down/i)).toBeInTheDocument();
    });
  });
});
