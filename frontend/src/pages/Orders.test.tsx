/** Tests for the Orders page. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { OrderRecord, OrdersResponse } from "../api/orders";
import type { ApiResponse } from "../api/client";

vi.mock("../api/orders", async () => {
  const actual = await vi.importActual<typeof import("../api/orders")>("../api/orders");
  return {
    ...actual,
    listOrders: vi.fn(),
  };
});

import { listOrders } from "../api/orders";
import Orders from "./Orders";

const listMock = vi.mocked(listOrders);

const ORDER: OrderRecord = {
  order_id: "ord-001",
  status: "paid",
  total_amount: 99,
  payment_source: "wechat",
  created_at: "2024-06-01T10:00:00Z",
  paid_at: "2024-06-01T10:01:00Z",
  items: [{ item_type: "subscription", item_id: "strat-1", item_name: "MA Cross", plan_type: "monthly", amount: 99 }],
};

function wrapOrders(list: OrderRecord[], total = 1, totalPages = 1): ApiResponse<OrdersResponse> {
  return {
    code: 0,
    message: "ok",
    data: { list, pagination: { page: 1, limit: 10, total, total_pages: totalPages } },
    timestamp: 0,
    request_id: "test",
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <Orders />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  listMock.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Orders — render", () => {
  it("renders the loading state while the query is pending", () => {
    listMock.mockReturnValue(new Promise(() => undefined));
    renderPage();
    expect(screen.getByText(/loading…/i)).toBeInTheDocument();
  });

  it("shows an empty-state message when there are no orders", async () => {
    listMock.mockResolvedValue(wrapOrders([]));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/no orders found/i)).toBeInTheDocument();
    });
  });

  it("renders a row for each order with order id, amount, and status badge", async () => {
    listMock.mockResolvedValue(wrapOrders([ORDER]));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("ord-001")).toBeInTheDocument();
    });
    expect(screen.getByText(/¥99\.00/)).toBeInTheDocument();
    expect(screen.getByText("PAID")).toBeInTheDocument();
    expect(screen.getByText(/MA Cross/)).toBeInTheDocument();
  });

  it("re-fetches with a status filter when a status tab is clicked", async () => {
    listMock.mockResolvedValue(wrapOrders([ORDER]));
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("ord-001")).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: /^Pending$/i }));
    await waitFor(() => {
      const lastCall = listMock.mock.calls[listMock.mock.calls.length - 1];
      expect(lastCall[0]?.status).toBe("pending");
    });
  });
});

describe("Orders — error", () => {
  it("surfaces an error message when the query rejects", async () => {
    listMock.mockRejectedValue(new Error("Boom"));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/boom/i)).toBeInTheDocument();
    });
  });
});
