/**
 * Tests for the backtest-sweep API client.
 *
 * The page (`BacktestSweepDetail`) consumes three endpoints:
 *   1. `listBacktestSweeps`        — paginated list with status filter
 *   2. `getBacktestSweep`          — detail by sweep_id
 *   3. `listBacktestSweepTrials`   — paginated trials within a sweep
 *
 * The page convention is zero-based `page` on the UI side, one-based
 * on the backend (see `backtests.test.ts` for the same convention).
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getBacktestSweep,
  listBacktestSweepTrials,
  listBacktestSweeps,
} from "./backtestSweeps";
import { lastFetchCall, mockJsonResponse } from "../test/fetch";

describe("backtestSweeps API", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  describe("listBacktestSweeps", () => {
    it("GETs /backtest-sweeps with no query string when called without params", async () => {
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

      await listBacktestSweeps();

      const [url] = lastFetchCall();
      expect(url).toBe("/v1/backtest-sweeps");
    });

    it("converts zero-based UI page to one-based backend and includes the status filter", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          mockJsonResponse({
            code: 0,
            message: "ok",
            data: { list: [], pagination: { page: 4, page_size: 10, total: 0, total_pages: 0 } },
            timestamp: 0,
            request_id: "r",
          }),
        ),
      );

      await listBacktestSweeps({ status: "running", page: 3, page_size: 10 });

      const [url] = lastFetchCall();
      expect(url).toBe("/v1/backtest-sweeps?status=running&page=4&page_size=10");
    });

    it("omits the status param when it is not provided", async () => {
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

      await listBacktestSweeps({ page: 0, page_size: 50 });

      const [url] = lastFetchCall();
      // page=0 UI → page=1 backend
      expect(url).toBe("/v1/backtest-sweeps?page=1&page_size=50");
    });
  });

  describe("getBacktestSweep", () => {
    it("GETs /backtest-sweeps/{id} and URL-encodes the sweep id", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          mockJsonResponse({
            code: 0,
            message: "ok",
            data: {
              sweep_id: "sweep/with spaces",
              search_type: "grid",
              search_spec: {},
              select_metric: "sharpe_ratio",
              maximize: true,
              status: "completed",
              total_trials: 0,
              completed_trials: 0,
              failed_trials: 0,
              best_trial_id: null,
              best_run_id: null,
              best_metric_value: null,
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

      await getBacktestSweep("sweep/with spaces");

      const [url, init] = lastFetchCall();
      expect(url).toBe("/v1/backtest-sweeps/sweep%2Fwith%20spaces");
      expect(init?.method).toBeUndefined();
    });
  });

  describe("listBacktestSweepTrials", () => {
    it("GETs /backtest-sweeps/{id}/trials with no query when called without params", async () => {
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

      await listBacktestSweepTrials("sweep-1");

      const [url] = lastFetchCall();
      expect(url).toBe("/v1/backtest-sweeps/sweep-1/trials");
    });

    it("includes the status filter and converts zero-based UI page", async () => {
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

      await listBacktestSweepTrials("sweep-1", { status: "failed", page: 1, page_size: 20 });

      const [url] = lastFetchCall();
      // page=1 UI → page=2 backend
      expect(url).toBe("/v1/backtest-sweeps/sweep-1/trials?status=failed&page=2&page_size=20");
    });
  });
});
