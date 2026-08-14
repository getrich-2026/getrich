import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  createBacktestJob,
  createWalkForwardJob,
  listBacktestJobs,
  type BacktestRunRequest,
  type WalkForwardRunRequest,
} from "./backtests";
import { lastFetchCall, mockJsonResponse } from "../test/fetch";

describe("backtest API", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("converts job list page from zero-based UI state to one-based backend query", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockJsonResponse({
          code: 0,
          message: "ok",
          data: {
            list: [],
            pagination: {
              page: 3,
              page_size: 20,
              total: 0,
              total_pages: 0,
            },
          },
          timestamp: 0,
          request_id: "req-1",
        }),
      ),
    );

    await listBacktestJobs({ job_type: "sweep", status: "completed", page: 2, page_size: 20 });

    const [url] = lastFetchCall();
    expect(url).toBe("/v1/backtest-jobs?job_type=sweep&status=completed&page=3&page_size=20");
  });

  it("sends an idempotency key when creating a backtest job", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockJsonResponse({
          code: 0,
          message: "ok",
          data: { job_id: "job-1", ref_id: "run-1", status: "queued" },
          timestamp: 0,
          request_id: "req-1",
        }),
      ),
    );
    const body: BacktestRunRequest = {
      strategy_name: "MACross",
      symbols: ["000001.SZ"],
      start: "2026-01-01T00:00:00+08:00",
      end: "2026-01-31T23:59:59+08:00",
      initial_cash: "1000000",
      freq: "1d",
      bar_loader: "pg",
      max_attempts: 1,
      extra_freqs: [],
      execution_lag_bars: 1,
      strategy_params: {},
      save_artifacts: false,
    };

    await createBacktestJob(body, "idem-1");

    const [url, init] = lastFetchCall();
    expect(url).toBe("/v1/backtest-jobs/backtest");
    expect(init?.method).toBe("POST");
    expect(init?.headers).toMatchObject({ "Idempotency-Key": "idem-1" });
    expect(init?.body).toBe(JSON.stringify(body));
  });

  it("posts walk-forward creation requests to the walk-forward endpoint", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockJsonResponse({
          code: 0,
          message: "ok",
          data: { job_id: "job-wf", ref_id: "wf-1", status: "queued" },
          timestamp: 0,
          request_id: "req-1",
        }),
      ),
    );
    const body: WalkForwardRunRequest = {
      strategy_name: "MACross",
      symbols: ["000001.SZ"],
      start: "2026-01-01T00:00:00+08:00",
      end: "2026-12-31T23:59:59+08:00",
      initial_cash: "1000000",
      freq: "1d",
      bar_loader: "pg",
      max_attempts: 1,
      search_spec: { space: { fast: [5, 10], slow: [20, 60] }, constraints: [] },
      train_months: 12,
      val_months: 3,
      step_months: 3,
      refit: "rolling",
      select_metric: "sharpe_ratio",
      maximize: true,
      fail_fast: false,
      strategy_params: {},
    };

    const res = await createWalkForwardJob(body, "idem-wf");

    const [url, init] = lastFetchCall();
    expect(res.job_id).toBe("job-wf");
    expect(url).toBe("/v1/backtest-jobs/walk-forward");
    expect(init?.method).toBe("POST");
    expect(init?.headers).toMatchObject({ "Idempotency-Key": "idem-wf" });
    expect(init?.body).toBe(JSON.stringify(body));
  });
});
