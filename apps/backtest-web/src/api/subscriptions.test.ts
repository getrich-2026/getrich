import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getSubscriptionStatus,
  subscribe,
  unsubscribe,
} from "./subscriptions";
import { lastFetchCall, mockJsonResponse } from "../test/fetch";

describe("subscriptions API", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("subscribe POSTs the request body to /strategies/{code}/subscribe", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockJsonResponse({
          code: 0,
          message: "ok",
          data: {
            subscription_id: "sub-1",
            status: "pending_payment",
            plan_type: "monthly",
            start_date: "2026-06-04",
            expire_date: "2026-07-04",
            payment: { order_id: "o-1", amount: 99, payment_source: "wechat", expire_time: "2026-06-04T01:00:00Z" },
          },
          timestamp: 0,
          request_id: "r",
        }),
      ),
    );
    const body = { plan_type: "monthly" as const, payment_source: "wechat" as const, auto_renew: true };

    await subscribe("MACross", body);

    const [url, init] = lastFetchCall();
    expect(url).toBe("/v1/strategies/MACross/subscribe");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(JSON.stringify(body));
  });

  it("unsubscribe with a reason sends {reason} in the body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockJsonResponse({
          code: 0,
          message: "ok",
          data: { strategy_id: "MACross", status: "cancelled", access_until: "2026-07-04" },
          timestamp: 0,
          request_id: "r",
        }),
      ),
    );

    await unsubscribe("MACross", "too expensive");

    const [url, init] = lastFetchCall();
    expect(url).toBe("/v1/strategies/MACross/unsubscribe");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(JSON.stringify({ reason: "too expensive" }));
  });

  it("unsubscribe without a reason sends an empty JSON object", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockJsonResponse({
          code: 0,
          message: "ok",
          data: { strategy_id: "MACross", status: "cancelled", access_until: "2026-07-04" },
          timestamp: 0,
          request_id: "r",
        }),
      ),
    );

    await unsubscribe("MACross");

    const [url, init] = lastFetchCall();
    expect(url).toBe("/v1/strategies/MACross/unsubscribe");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe("{}");
  });

  it("getSubscriptionStatus GETs /strategies/{code}/subscription", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockJsonResponse({
          code: 0,
          message: "ok",
          data: {
            is_subscribed: false,
            subscription_id: null,
            status: null,
            plan_type: null,
            start_date: null,
            expire_date: null,
            auto_renew: false,
            subscription_price: { monthly: 99, yearly: 999 },
          },
          timestamp: 0,
          request_id: "r",
        }),
      ),
    );

    await getSubscriptionStatus("MACross");

    const [url, init] = lastFetchCall();
    expect(url).toBe("/v1/strategies/MACross/subscription");
    expect(init?.method).toBeUndefined();
  });
});
