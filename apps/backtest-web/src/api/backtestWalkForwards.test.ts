/**
 * Tests for the backtest-walk-forward API client.
 *
 * The page (`BacktestWalkForwardDetail`) consumes four endpoints:
 *   1. `listBacktestWalkForwards`               — paginated list
 *   2. `getBacktestWalkForward`                 — detail by id
 *   3. `listBacktestWalkForwardWindows`         — paginated windows
 *   4. `getBacktestWalkForwardOosEquityCurve`   — out-of-sample equity curve
 *
 * Same zero-based UI page → one-based backend convention as the
 * other backtest API modules.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getBacktestWalkForward,
  getBacktestWalkForwardOosEquityCurve,
  listBacktestWalkForwardWindows,
  listBacktestWalkForwards,
} from "./backtestWalkForwards";
import { lastFetchCall, mockJsonResponse } from "../test/fetch";

describe("backtestWalkForwards API", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  describe("listBacktestWalkForwards", () => {
    it("GETs /backtest-walk-forwards with no query string when called without params", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          mockJsonResponse({
            code: 0,
            message: "ok",
            data: { list: [], pagination: { page: 1, page_size: 20, total: 0, total_pages: 0 } },
            timestamp: 0,
            request_id: "r",
          }),
        ),
      );

      await listBacktestWalkForwards();

      const [url] = lastFetchCall();
      expect(url).toBe("/v1/backtest-walk-forwards");
    });

    it("converts zero-based UI page to one-based backend and includes the status filter", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          mockJsonResponse({
            code: 0,
            message: "ok",
            data: { list: [], pagination: { page: 2, page_size: 20, total: 0, total_pages: 0 } },
            timestamp: 0,
            request_id: "r",
          }),
        ),
      );

      await listBacktestWalkForwards({ status: "completed", page: 1, page_size: 20 });

      const [url] = lastFetchCall();
      expect(url).toBe("/v1/backtest-walk-forwards?status=completed&page=2&page_size=20");
    });
  });

  describe("getBacktestWalkForward", () => {
    it("GETs /backtest-walk-forwards/{id} and URL-encodes the id", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          mockJsonResponse({
            code: 0,
            message: "ok",
            data: {
              walk_forward_id: "wf-1",
              search_type: "grid",
              search_spec: {},
              select_metric: "sharpe_ratio",
              maximize: true,
              refit: "rolling",
              status: "completed",
              total_windows: 0,
              completed_windows: 0,
              failed_windows: 0,
              mean_validation_metric: null,
              created_at: "2026-01-01T00:00:00+08:00",
              completed_at: null,
              updated_at: "2026-01-01T00:00:00+08:00",
              summary_json: {},
              job_id: null,
              progress: null,
              job_status: null,
            },
            timestamp: 0,
            request_id: "r",
          }),
        ),
      );

      await getBacktestWalkForward("wf-1");

      const [url, init] = lastFetchCall();
      expect(url).toBe("/v1/backtest-walk-forwards/wf-1");
      expect(init?.method).toBeUndefined();
    });

    it("URL-encodes special characters in the walk-forward id", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          mockJsonResponse({
            code: 0,
            message: "ok",
            data: {
              walk_forward_id: "wf/a b",
              search_type: "grid",
              search_spec: {},
              select_metric: "sharpe_ratio",
              maximize: true,
              refit: "rolling",
              status: "queued",
              total_windows: 0,
              completed_windows: 0,
              failed_windows: 0,
              mean_validation_metric: null,
              created_at: "2026-01-01T00:00:00+08:00",
              completed_at: null,
              updated_at: "2026-01-01T00:00:00+08:00",
              summary_json: {},
              job_id: null,
              progress: null,
              job_status: null,
            },
            timestamp: 0,
            request_id: "r",
          }),
        ),
      );

      await getBacktestWalkForward("wf/a b");

      const [url] = lastFetchCall();
      expect(url).toBe("/v1/backtest-walk-forwards/wf%2Fa%20b");
    });
  });

  describe("listBacktestWalkForwardWindows", () => {
    it("GETs /backtest-walk-forwards/{id}/windows with no query when called without params", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          mockJsonResponse({
            code: 0,
            message: "ok",
            data: { list: [], pagination: { page: 1, page_size: 20, total: 0, total_pages: 0 } },
            timestamp: 0,
            request_id: "r",
          }),
        ),
      );

      await listBacktestWalkForwardWindows("wf-1");

      const [url] = lastFetchCall();
      expect(url).toBe("/v1/backtest-walk-forwards/wf-1/windows");
    });

    it("includes the status filter and converts zero-based UI page", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          mockJsonResponse({
            code: 0,
            message: "ok",
            data: { list: [], pagination: { page: 3, page_size: 10, total: 0, total_pages: 0 } },
            timestamp: 0,
            request_id: "r",
          }),
        ),
      );

      await listBacktestWalkForwardWindows("wf-1", { status: "failed", page: 2, page_size: 10 });

      const [url] = lastFetchCall();
      // page=2 UI → page=3 backend
      expect(url).toBe("/v1/backtest-walk-forwards/wf-1/windows?status=failed&page=3&page_size=10");
    });
  });

  describe("getBacktestWalkForwardOosEquityCurve", () => {
    it("GETs /backtest-walk-forwards/{id}/oos-equity-curve with no query", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          mockJsonResponse({
            code: 0,
            message: "ok",
            data: { points: [], total_points: 0 },
            timestamp: 0,
            request_id: "r",
          }),
        ),
      );

      await getBacktestWalkForwardOosEquityCurve("wf-1");

      const [url, init] = lastFetchCall();
      expect(url).toBe("/v1/backtest-walk-forwards/wf-1/oos-equity-curve");
      expect(init?.method).toBeUndefined();
    });
  });
});
