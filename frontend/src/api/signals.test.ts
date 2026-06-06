import { beforeEach, describe, expect, it, vi } from "vitest";
import { executeSignal, getSignalDetail, markSignalRead } from "./signals";
import { lastFetchCall, mockJsonResponse } from "../test/fetch";

describe("signals API", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("getSignalDetail GETs /signals/{code} with URL-encoded id", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockJsonResponse({
          code: 0,
          message: "ok",
          data: { id: "sig-1" },
          timestamp: 0,
          request_id: "r",
        }),
      ),
    );

    await getSignalDetail("sig/with/slash");

    const [url, init] = lastFetchCall();
    expect(url).toBe("/v1/signals/sig%2Fwith%2Fslash");
    expect(init?.method).toBeUndefined();
    expect(init?.body).toBeUndefined();
  });

  it("markSignalRead POSTs to /signals/{code}/read with no body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockJsonResponse({
          code: 0,
          message: "ok",
          data: { signal_id: "sig-1", is_read: true, read_at: "now", remaining_unread: 0 },
          timestamp: 0,
          request_id: "r",
        }),
      ),
    );

    await markSignalRead("sig-1");

    const [url, init] = lastFetchCall();
    expect(url).toBe("/v1/signals/sig-1/read");
    expect(init?.method).toBe("POST");
    // markSignalRead sets the method only; no body is sent.
    expect(init?.body).toBeUndefined();
  });

  it("executeSignal POSTs the execution body to /signals/{code}/execute", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockJsonResponse({
          code: 0,
          message: "ok",
          data: {
            signal_id: "sig-1",
            is_executed: true,
            executed_price: 10.5,
            executed_at: "2026-06-04T00:00:00Z",
            slippage: 0.01,
            slippage_pct: 0.001,
          },
          timestamp: 0,
          request_id: "r",
        }),
      ),
    );
    const body = { executed_price: 10.5, executed_quantity: 100, note: "filled" };

    await executeSignal("sig-1", body);

    const [url, init] = lastFetchCall();
    expect(url).toBe("/v1/signals/sig-1/execute");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(JSON.stringify(body));
  });
});
