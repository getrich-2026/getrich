import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getEquityCurve,
  getStrategyDetail,
  listSignals,
  listStrategies,
  listTrades,
  updateStrategy,
} from "./strategies";
import { lastFetchCall, mockJsonResponse } from "../test/fetch";

describe("strategies API", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("listStrategies GETs /strategies and unwraps .data.list", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockJsonResponse({
          code: 0,
          message: "ok",
          data: {
            list: [
              {
                id: "s-1",
                name: "MA Cross",
                subscriber_count: 5,
                is_subscribed: false,
                subscription_price: { monthly: 0, yearly: 0 },
              },
            ],
            pagination: { page: 1, page_size: 20, total: 1, total_pages: 1 },
            order: [],
          },
          timestamp: 0,
          request_id: "r",
        }),
      ),
    );

    const result = await listStrategies();

    const [url] = lastFetchCall();
    expect(url).toBe("/v1/strategies");
    expect(result).toHaveLength(1);
    expect(result[0]?.id).toBe("s-1");
  });

  it("listSignals builds query string from optional filters", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockJsonResponse({
          list: [],
          pagination: { page: 1, page_size: 20, total: 0, total_pages: 0 },
        }),
      ),
    );

    await listSignals("MACross", {
      limit: 50,
      offset: 100,
      start_date: "2026-01-01",
      end_date: "2026-12-31",
      action: "buy",
      result: "win",
    });

    const [url] = lastFetchCall();
    expect(url).toBe(
      "/v1/strategies/MACross/signals?limit=50&offset=100&start_date=2026-01-01&end_date=2026-12-31&action=buy&result=win",
    );
  });

  it("listSignals omits filters that are not provided", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockJsonResponse({
          list: [],
          pagination: { page: 1, page_size: 20, total: 0, total_pages: 0 },
        }),
      ),
    );

    await listSignals("MACross");

    const [url] = lastFetchCall();
    expect(url).toBe("/v1/strategies/MACross/signals");
  });

  it("listTrades builds query string from optional filters", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockJsonResponse({
          list: [],
          pagination: { page: 1, page_size: 20, total: 0, total_pages: 0 },
        }),
      ),
    );

    await listTrades("MACross", { limit: 25, action: "sell" });

    const [url] = lastFetchCall();
    expect(url).toBe("/v1/strategies/MACross/trades?limit=25&action=sell");
  });

  it("getStrategyDetail GETs /strategies/{code}", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockJsonResponse({
          code: 0,
          message: "ok",
          data: { id: "s-1", name: "MA Cross" },
          timestamp: 0,
          request_id: "r",
        }),
      ),
    );

    await getStrategyDetail("MACross");

    const [url, init] = lastFetchCall();
    expect(url).toBe("/v1/strategies/MACross");
    expect(init?.method).toBeUndefined();
  });

  it("updateStrategy PUTs the body to /strategies/{code}", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockJsonResponse({
          code: 0,
          message: "ok",
          data: { id: "s-1" },
          timestamp: 0,
          request_id: "r",
        }),
      ),
    );
    const body = { name: "Renamed", description: "new desc" };

    await updateStrategy("MACross", body);

    const [url, init] = lastFetchCall();
    expect(url).toBe("/v1/strategies/MACross");
    expect(init?.method).toBe("PUT");
    expect(init?.body).toBe(JSON.stringify(body));
  });

  it("getEquityCurve serialises booleans and omits missing params", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockJsonResponse({
          code: 0,
          message: "ok",
          data: { strategy_id: "s-1", period: {}, equity_curve: [], benchmark_curve: [], drawdown_curve: [], total_points: 0 },
          timestamp: 0,
          request_id: "r",
        }),
      ),
    );

    await getEquityCurve("MACross", {
      period: "1y",
      start_date: "2026-01-01",
      end_date: "2026-12-31",
      include_benchmark: true,
      include_drawdown: false,
    });

    const [url] = lastFetchCall();
    expect(url).toBe(
      "/v1/strategies/MACross/equity-curve?period=1y&start_date=2026-01-01&end_date=2026-12-31&include_benchmark=true&include_drawdown=false",
    );
  });
});
