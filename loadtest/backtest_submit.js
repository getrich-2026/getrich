// backtest_submit.js — backtest job submit + status polling.
//
// Purpose:
//   Simulate a researcher iterating on backtests: they click
//   "Run", wait for the result, then click "Run" again with
//   tweaked params. We POST a backtest, poll its status until
//   it completes (or 60s timeout), then submit another.
//
// Why this is interesting:
//   The submit endpoint is light (a single INSERT), but the
//   poll endpoint is the SSE-backed GET /v1/backtest-jobs/{id}
//   which keeps a worker alive. 50 concurrent in-flight jobs
//   stress the worker pool more than the API.
//
// SLO:
//   - p99 submit latency < 800 ms (single INSERT)
//   - p99 status-poll latency < 200 ms
//   - 0 unhandled 5xx (any 5xx is a worker-pool exhaustion)
//
// Run:
//   k6 run loadtest/backtest_submit.js

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate } from 'k6/metrics';

const submits = new Counter('backtest_submits');
const completions = new Counter('backtest_completions');
const errorRate = new Rate('errors');

export const options = {
    vus: __ENV.K6_VUS ? parseInt(__ENV.K6_VUS, 10) : 5,
    duration: __ENV.K6_DURATION || '2m',

    thresholds: {
        'http_req_duration{endpoint:submit}': ['p(99)<800'],
        'http_req_duration{endpoint:poll}': ['p(99)<200'],
        // 5xx from the submit endpoint usually means the
        // worker pool is exhausted (or PG/CH is down).
        'errors': ['rate<0.05'],
    },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const EMAIL = __ENV.TEST_USER_EMAIL || 'loadtest@example.com';
const PASSWORD = __ENV.TEST_USER_PASSWORD || 'loadtest-pw-12345';

export function setup() {
    const res = http.post(
        `${BASE_URL}/v1/auth/login`,
        JSON.stringify({ email: EMAIL, password: PASSWORD }),
        { headers: { 'Content-Type': 'application/json' } },
    );
    if (res.status !== 200) {
        throw new Error(`auth setup failed: ${res.status}`);
    }
    return { token: res.json('access_token') };
}

function authHeaders(token) {
    return {
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
        },
    };
}

export default function (data) {
    const headers = authHeaders(data.token);

    // 1. Submit a backtest
    const submitRes = http.post(
        `${BASE_URL}/v1/backtest-jobs`,
        JSON.stringify({
            // A deliberately tiny config — the actual strategy
            // spec is opaque to the load test. We use the
            // smallest valid shape so a failed submit is
            // obviously a backend bug, not a payload bug.
            strategy_code: 'ma_cross_5_20',
            start_date: '2024-01-01',
            end_date: '2024-06-30',
            initial_capital: 1000000,
            params: { fast: 5, slow: 20 },
        }),
        { ...headers, tags: { endpoint: 'submit' } },
    );
    submits.add(1);
    const submitOk = check(submitRes, {
        'submit status 201': (r) => r.status === 201,
        'submit returns job id': (r) => {
            try {
                return r.json('id') !== undefined;
            } catch (_e) {
                return false;
            }
        },
    });
    errorRate.add(!submitOk);
    if (!submitOk) {
        sleep(2);
        return;
    }

    const jobId = submitRes.json('id');

    // 2. Poll until done. We use a simple exponential-ish
    //    backoff: 0.5s, 1s, 1s, 2s, 2s, 4s — capped at 4s
    //    per poll. We time out after 30 polls (~ 60s of
    //    wall time at the 4s cap).
    const POLL_DELAYS = [0.5, 1, 1, 2, 2, 4];
    let lastStatus = null;
    for (let i = 0; i < 30; i++) {
        const delay = POLL_DELAYS[Math.min(i, POLL_DELAYS.length - 1)];
        sleep(delay);

        const pollRes = http.get(
            `${BASE_URL}/v1/backtest-jobs/${jobId}`,
            { ...headers, tags: { endpoint: 'poll' } },
        );
        const pollOk = check(pollRes, {
            'poll status 200': (r) => r.status === 200,
        });
        errorRate.add(!pollOk);
        if (!pollOk) {
            break;
        }
        try {
            lastStatus = pollRes.json('status');
        } catch (_e) {
            lastStatus = null;
        }
        if (lastStatus === 'completed' || lastStatus === 'failed') {
            completions.add(1);
            break;
        }
    }

    // Note: we don't fail the test on 'failed' status —
    // a real backtest may have bad data. We only fail on
    // HTTP 5xx (the `errors` rate metric).
    sleep(1);
}
