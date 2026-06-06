/** Tests for the Signals list page. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SignalRecord, StrategySummary } from "../api/strategies";
import type { PaginatedResponse } from "../api/client";

vi.mock("../api/strategies", async () => {
  const actual = await vi.importActual<typeof import("../api/strategies")>(
    "../api/strategies",
  );
  return {
    ...actual,
    listStrategies: vi.fn(),
    listSignals: vi.fn(),
  };
});

import { listSignals, listStrategies } from "../api/strategies";
import Signals from "./Signals";

const listStratMock = vi.mocked(listStrategies);
const listSignalsMock = vi.mocked(listSignals);

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

const SIGNAL: SignalRecord = {
  id: "sig-1",
  signal_type: "entry",
  action: "buy",
  symbol: "000001.SZ",
  trigger_price: 10.5,
  confidence: 0.8,
  urgency: "high",
  trigger_time: "2024-06-01T09:30:00+08:00",
  is_read: false,
  is_executed: false,
  status: "active",
};

// Real `PaginatedResponse<T>` shape is `{ data: T[], total, limit, offset }`.
// The page reads `data.data.map(...)` so we hand back the paginated object
// directly (not wrapped in `ApiResponse`).
function wrapPaginated<T>(items: T[], total = items.length): PaginatedResponse<T> {
  return {
    data: items,
    total,
    limit: 20,
    offset: 0,
  };
}

function renderPage(initial = "/signals") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <QueryClientProvider client={queryClient}>
        <Signals />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  listStratMock.mockReset();
  listSignalsMock.mockReset();
  listStratMock.mockResolvedValue(STRATEGIES);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Signals — render", () => {
  it("shows a 'select a strategy' hint when no strategy is chosen", async () => {
    listSignalsMock.mockResolvedValue(wrapPaginated<SignalRecord>([]));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/select a strategy to view its signals/i)).toBeInTheDocument();
    });
    expect(listSignalsMock).not.toHaveBeenCalled();
  });

  it("auto-selects the strategy from the ?strategy= query string", async () => {
    listSignalsMock.mockResolvedValue(wrapPaginated<SignalRecord>([SIGNAL]));
    renderPage("/signals?strategy=s-1");
    await waitFor(() => {
      expect(listSignalsMock).toHaveBeenCalledWith(
        "s-1",
        expect.objectContaining({ limit: 20, offset: 0 }),
      );
    });
  });

  it("renders a row for each signal returned by the API", async () => {
    listSignalsMock.mockResolvedValue(wrapPaginated<SignalRecord>([SIGNAL]));
    renderPage("/signals?strategy=s-1");
    await waitFor(() => {
      expect(screen.getByText("sig-1")).toBeInTheDocument();
    });
    // Trigger price formatted as decimal.
    expect(screen.getByText("10.5")).toBeInTheDocument();
    // Confidence displayed as percentage.
    expect(screen.getByText(/80%/)).toBeInTheDocument();
  });

  it("shows an empty-state row when the strategy has no signals", async () => {
    listSignalsMock.mockResolvedValue(wrapPaginated<SignalRecord>([]));
    renderPage("/signals?strategy=s-1");
    await waitFor(() => {
      expect(screen.getByText(/no signals found/i)).toBeInTheDocument();
    });
  });

  it("changes the strategy when the picker changes", async () => {
    listStratMock.mockResolvedValue([
      ...STRATEGIES,
      {
        id: "s-2",
        name: "Beta",
        code: "BETA",
        subscriber_count: 0,
        is_subscribed: false,
        subscription_price: { monthly: 0, yearly: 0 },
      },
    ]);
    listSignalsMock.mockResolvedValue(wrapPaginated<SignalRecord>([]));
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("option", { name: /Alpha/i })).toBeInTheDocument();
    });
    await user.selectOptions(screen.getByLabelText(/Strategy:/i), "s-1");
    await waitFor(() => {
      expect(listSignalsMock).toHaveBeenCalledWith("s-1", expect.anything());
    });
  });
});

describe("Signals — error", () => {
  it("surfaces an error message when the signals query rejects", async () => {
    listSignalsMock.mockRejectedValue(new Error("Network down"));
    renderPage("/signals?strategy=s-1");
    await waitFor(() => {
      expect(screen.getByText(/network down/i)).toBeInTheDocument();
    });
  });
});
