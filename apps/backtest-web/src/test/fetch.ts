/**
 * Shared test helpers for mocking `fetch` calls in API module tests.
 *
 * The `vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockJsonResponse(...)))`
 * pattern plus `lastFetchCall()` assertion helper is repeated across all
 * 7 API test files; this module is the single source of truth.
 *
 * See `frontend/src/api/*.test.ts` for usage examples.
 */

import { vi } from "vitest";

/**
 * Build a `Response` with a JSON-encoded body. Defaults to HTTP 200; pass
 * an explicit `status` (e.g. 400 / 401 / 500) to exercise error paths.
 */
export function mockJsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/**
 * Return the URL and `RequestInit` from the most recent `fetch` call.
 *
 * The pattern is `vi.stubGlobal("fetch", vi.fn().mockResolvedValue(...))`
 * followed by the API function under test, then
 * `const [url, init] = lastFetchCall()`.
 *
 * Throws if no fetch call has been recorded — use this to assert that
 * the API function actually issued a request.
 */
export function lastFetchCall(): [string, RequestInit | undefined] {
  const calls = vi.mocked(fetch).mock.calls;
  const last = calls.at(-1);
  if (!last) throw new Error("fetch was not called");
  return last as [string, RequestInit | undefined];
}
