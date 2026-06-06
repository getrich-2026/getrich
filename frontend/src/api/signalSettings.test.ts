import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getStrategySignalSettings,
  getUserSignalSettings,
  updateStrategySignalSettings,
  updateUserSignalSettings,
} from "./signalSettings";
import { lastFetchCall, mockJsonResponse } from "../test/fetch";

describe("signalSettings API", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("getUserSignalSettings GETs /user/signal-settings with no body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockJsonResponse({
          code: 0,
          message: "ok",
          data: { push_enabled: true, channels: {} as never, global_settings: {} as never, strategy_overrides: [] },
          timestamp: 0,
          request_id: "r",
        }),
      ),
    );

    await getUserSignalSettings();

    const [url, init] = lastFetchCall();
    expect(url).toBe("/v1/user/signal-settings");
    expect(init?.method).toBeUndefined();
    expect(init?.body).toBeUndefined();
  });

  it("updateUserSignalSettings PUTs the body to /user/signal-settings", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockJsonResponse({
          code: 0,
          message: "ok",
          data: { updated: true },
          timestamp: 0,
          request_id: "r",
        }),
      ),
    );
    const body = { push_enabled: false, channels: { email: true } as never };

    await updateUserSignalSettings(body);

    const [url, init] = lastFetchCall();
    expect(url).toBe("/v1/user/signal-settings");
    expect(init?.method).toBe("PUT");
    expect(init?.body).toBe(JSON.stringify(body));
  });

  it("getStrategySignalSettings GETs /strategies/{code}/signal-settings with URL-encoding", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockJsonResponse({
          code: 0,
          message: "ok",
          data: { strategy_id: "MACross", enabled: true, channels: {} as never, urgency_filter: [], confidence_threshold: 0, notify_entry_only: false },
          timestamp: 0,
          request_id: "r",
        }),
      ),
    );

    await getStrategySignalSettings("MACross v2/alpha");

    const [url, init] = lastFetchCall();
    expect(url).toBe("/v1/strategies/MACross%20v2%2Falpha/signal-settings");
    expect(init?.method).toBeUndefined();
  });

  it("updateStrategySignalSettings PUTs the body to the encoded strategy URL", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockJsonResponse({
          code: 0,
          message: "ok",
          data: { strategy_id: "MACross", updated: true },
          timestamp: 0,
          request_id: "r",
        }),
      ),
    );
    const body = { enabled: false, notify_entry_only: true };

    await updateStrategySignalSettings("MACross", body);

    const [url, init] = lastFetchCall();
    expect(url).toBe("/v1/strategies/MACross/signal-settings");
    expect(init?.method).toBe("PUT");
    expect(init?.body).toBe(JSON.stringify(body));
  });
});
