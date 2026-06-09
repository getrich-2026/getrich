/**
 * Tests for the core `apiFetch` client — specifically the 401
 * refresh-token interceptor, error mapping, and token injection.
 *
 * These cover the most security-sensitive part of the frontend: if the
 * 401 interceptor regresses, the whole auth flow breaks (infinite
 * refresh loops, leaked session, redirect on every request).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiClientError,
  apiFetch,
  clearAccessToken,
  clearRefreshToken,
  clearStoredUser,
  setAccessToken,
  setRefreshToken,
  setStoredUser,
} from "./client";

function okResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function errorResponse(status: number, detail = "boom"): Response {
  return new Response(JSON.stringify({ detail }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("apiFetch — happy path", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    clearAccessToken();
    clearRefreshToken();
    clearStoredUser();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("GETs the path with the configured /v1 prefix and parses the JSON body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(okResponse({ code: 0, message: "ok", data: 42 })),
    );

    const result = await apiFetch<{ code: number; data: number }>("/health");

    const calls = vi.mocked(fetch).mock.calls;
    expect(calls).toHaveLength(1);
    expect(calls[0]?.[0]).toBe("/v1/health");
    expect(result.data).toBe(42);
  });

  it("injects the Authorization header when an access token is cached", async () => {
    setAccessToken("access-1");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okResponse({ ok: true })));

    await apiFetch("/me");

    const [, init] = vi.mocked(fetch).mock.calls[0]!;
    const headers = init?.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer access-1");
  });

  it("omits the Authorization header when no access token is cached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okResponse({ ok: true })));

    await apiFetch("/me");

    const [, init] = vi.mocked(fetch).mock.calls[0]!;
    const headers = init?.headers as Record<string, string>;
    expect(headers["Authorization"]).toBeUndefined();
  });
});

describe("apiFetch — non-401 error mapping", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    clearAccessToken();
    clearRefreshToken();
    clearStoredUser();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("throws ApiClientError with status and JSON detail on 400", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(errorResponse(400, "bad input")));

    await expect(apiFetch("/anything")).rejects.toMatchObject({
      name: "ApiClientError",
      status: 400,
      detail: "bad input",
    });
  });

  it("falls back to statusText when the error body is not JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("not json", { status: 500, statusText: "Internal Server Error" }),
      ),
    );

    await expect(apiFetch("/anything")).rejects.toBeInstanceOf(ApiClientError);
    await expect(apiFetch("/anything")).rejects.toMatchObject({ status: 500 });
  });

  it("uses statusText when the JSON body has no `detail` field", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ message: "ignored" }), {
          status: 409,
          statusText: "Conflict",
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(apiFetch("/anything")).rejects.toMatchObject({
      status: 409,
      detail: "Conflict",
    });
  });
});

describe("apiFetch — 401 refresh interceptor", () => {
  let originalLocation: Location;
  let locationHref: string;

  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    clearAccessToken();
    clearRefreshToken();
    clearStoredUser();
    vi.restoreAllMocks();

    // Stub window.location.href so we can assert the redirect target
    // without actually navigating. jsdom does not let us assign to
    // window.location, so we replace the href setter via Object.defineProperty.
    originalLocation = window.location;
    locationHref = "/some-page";
    Object.defineProperty(window, "location", {
      configurable: true,
      writable: true,
      value: { ...originalLocation, get href() { return locationHref; }, set href(v: string) { locationHref = v; } },
    });
  });

  afterEach(() => {
    Object.defineProperty(window, "location", {
      configurable: true,
      writable: true,
      value: originalLocation,
    });
    vi.unstubAllGlobals();
  });

  it("retries the original request once when refresh succeeds and returns the retried body", async () => {
    setAccessToken("old-access");
    setRefreshToken("old-refresh");
    setStoredUser({ id: "u-1", email: "alice@example.com", name: "Alice" });

    // Sequence:
    //   call 1: original GET /v1/strategies → 401
    //   call 2: POST /v1/auth/refresh → 200 with new tokens
    //   call 3: retried GET /v1/strategies → 200 with body
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(errorResponse(401, "expired"))
      .mockResolvedValueOnce(
        okResponse({
          code: 0,
          message: "ok",
          data: {
            access_token: "new-access",
            refresh_token: "new-refresh",
            user: { id: "u-1", email: "alice@example.com", name: "Alice" },
          },
        }),
      )
      .mockResolvedValueOnce(
        okResponse({
          code: 0,
          message: "ok",
          data: { list: ["x"], pagination: {} },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await apiFetch<{ data: { list: string[] } }>("/strategies");

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/v1/strategies");
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/v1/auth/refresh");
    expect(fetchMock.mock.calls[2]?.[0]).toBe("/v1/strategies");

    // The retry must use the *new* access token
    const retryHeaders = fetchMock.mock.calls[2]?.[1]?.headers as Record<string, string>;
    expect(retryHeaders["Authorization"]).toBe("Bearer new-access");

    // The auth store must be updated with the new tokens
    expect(sessionStorage.getItem("getrich_access_token")).toBe("new-access");
    expect(localStorage.getItem("getrich_refresh_token")).toBe("new-refresh");

    // And the unwrapped body is returned
    expect(result.data.list).toEqual(["x"]);
  });

  it("clears auth state, redirects to /login, and throws when there is no refresh token", async () => {
    setAccessToken("stale");
    // No refresh token set

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(errorResponse(401, "expired")));

    await expect(apiFetch("/strategies")).rejects.toMatchObject({
      name: "ApiClientError",
      status: 401,
      detail: "session expired, please log in again",
    });

    // Only the original request was made (no refresh attempt)
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);

    // Auth state was cleared
    expect(sessionStorage.getItem("getrich_access_token")).toBeNull();
    expect(localStorage.getItem("getrich_refresh_token")).toBeNull();
    expect(sessionStorage.getItem("getrich_user")).toBeNull();

    // Window was redirected to /login
    expect(locationHref).toBe("/login");
  });

  it("clears auth state when the refresh call itself returns non-OK", async () => {
    setAccessToken("stale");
    setRefreshToken("revoked");

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(errorResponse(401, "expired")) // original
      .mockResolvedValueOnce(errorResponse(401, "refresh revoked")); // refresh
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiFetch("/strategies")).rejects.toBeInstanceOf(ApiClientError);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(sessionStorage.getItem("getrich_access_token")).toBeNull();
    expect(localStorage.getItem("getrich_refresh_token")).toBeNull();
    expect(locationHref).toBe("/login");
  });

  it("clears auth state when the refresh call throws (network error)", async () => {
    setAccessToken("stale");
    setRefreshToken("revoked");

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(errorResponse(401, "expired")) // original
      .mockRejectedValueOnce(new Error("ECONNREFUSED")); // refresh network error
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiFetch("/strategies")).rejects.toBeInstanceOf(ApiClientError);

    // The catch wraps the network error and re-throws ApiClientError
    expect(sessionStorage.getItem("getrich_access_token")).toBeNull();
    expect(locationHref).toBe("/login");
  });

  it("does NOT attempt refresh when the failing path is /auth/refresh itself", async () => {
    setRefreshToken("stale");

    // /auth/refresh returns 401; the interceptor must short-circuit
    // and throw without trying to refresh again (avoids infinite loop).
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(errorResponse(401, "bad refresh")));

    await expect(apiFetch("/auth/refresh")).rejects.toBeInstanceOf(ApiClientError);

    // Only one call — the original refresh attempt, no second refresh.
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
  });

  it("does NOT attempt refresh when the failing path is /auth/login", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(errorResponse(401, "bad creds")));

    await expect(apiFetch("/auth/login")).rejects.toBeInstanceOf(ApiClientError);

    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
  });
});

describe("apiFetch — token store clearing on logout", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
  });

  it("clearAccessToken / clearRefreshToken / clearStoredUser wipe both caches", () => {
    setAccessToken("a");
    setRefreshToken("r");
    setStoredUser({ id: "u-1", email: "x@x", name: "X" });

    clearAccessToken();
    clearRefreshToken();
    clearStoredUser();

    expect(sessionStorage.getItem("getrich_access_token")).toBeNull();
    expect(localStorage.getItem("getrich_refresh_token")).toBeNull();
    expect(sessionStorage.getItem("getrich_user")).toBeNull();
  });
});
