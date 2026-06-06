import { beforeEach, describe, expect, it, vi } from "vitest";
import { listOrders } from "./orders";
import { lastFetchCall, mockJsonResponse } from "../test/fetch";

describe("orders API", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("builds a URL with no query string when called without params", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockJsonResponse({
          code: 0,
          message: "ok",
          data: { list: [], pagination: { page: 1, limit: 20, total: 0, total_pages: 0 } },
          timestamp: 0,
          request_id: "r",
        }),
      ),
    );

    await listOrders();

    const [url] = lastFetchCall();
    expect(url).toBe("/v1/user/orders");
  });

  it("omits the status query param when the user passes status='all' (UI sentinel)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockJsonResponse({
          code: 0,
          message: "ok",
          data: { list: [], pagination: { page: 1, limit: 20, total: 0, total_pages: 0 } },
          timestamp: 0,
          request_id: "r",
        }),
      ),
    );

    await listOrders({ status: "all" });

    const [url] = lastFetchCall();
    // The "all" sentinel is a UI-only concept and is dropped before
    // serialising the query string. No page/limit passed → no params.
    expect(url).toBe("/v1/user/orders");
  });

  it("converts page from zero-based UI to one-based backend and includes the status filter", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockJsonResponse({
          code: 0,
          message: "ok",
          data: { list: [], pagination: { page: 2, limit: 50, total: 0, total_pages: 0 } },
          timestamp: 0,
          request_id: "r",
        }),
      ),
    );

    await listOrders({ status: "paid", page: 1, limit: 50 });

    const [url] = lastFetchCall();
    expect(url).toBe("/v1/user/orders?status=paid&page=2&limit=50");
  });
});
