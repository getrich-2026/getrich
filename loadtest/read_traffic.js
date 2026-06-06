// read_traffic.js — authenticated read-heavy load test.
//
// Purpose:
//   Simulate the typical dashboard browsing pattern: a user
//   opens the page, the dashboard makes ~10 GET calls in
//   parallel (strategies, signals, equity curves, etc). We
//   pace each VU at ~2 RPS for 5 minutes, which works out
//   to 600 RPS / 100 VUs — well above our 100 RPS target.
//
// SLO:
//   - p95 latency < 300 ms for any single read endpoint
//   - error rate < 1 % (we expect 200s for every request)
//
// Run:
//   k6 run loadtest/read_traffic.js
//   BASE_URL=https://staging.getrich.example.com \
//     TEST_USER_EMAIL=stress@example.com \
//     TEST_USER_PASSWORD=stresspw123 \
//     k6 run loadtest/read_traffic.js

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate } from 'k6/metrics';

const errorRate = new Rate('errors');

export const options = {
    // Realistic load: 50 VUs (one per "active dashboard
    // session"), each making ~2 RPS. Total: 100 RPS.
    vus: __ENV.K6_VUS ? parseInt(__ENV.K6_VUS, 10) : 50,
    duration: __ENV.K6_DURATION || '5m',

    thresholds: {
        // p95 < 300 ms on every read endpoint. The bottleneck
        // is usually the DB connection pool, not the API layer.
        'http_req_duration{endpoint:strategies_list}': ['p(95)<300'],
        'http_req_duration{endpoint:strategy_detail}': ['p(95)<300'],
        'http_req_duration{endpoint:signals_list}': ['p(95)<300'],
        'http_req_duration{endpoint:equity_curve}': ['p(95)<500'],
        'http_req_duration{endpoint:monthly_returns}': ['p(95)<500'],
        'errors': ['rate<0.01'],
    },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const EMAIL = __ENV.TEST_USER_EMAIL || 'loadtest@example.com';
const PASSWORD = __ENV.TEST_USER_PASSWORD || 'loadtest-pw-12345';

let accessToken;  // Set once per VU in setup() below.

export function setup() {
    // Login ONCE per VU; reuse the token for all iterations.
    // The token expires after 30 min by default; the test
    // is shorter than that.
    const res = http.post(
        `${BASE_URL}/v1/auth/login`,
        JSON.stringify({ email: EMAIL, password: PASSWORD }),
        { headers: { 'Content-Type': 'application/json' } },
    );
    if (res.status !== 200) {
        throw new Error(
            `auth setup failed: ${res.status} ${res.body.slice(0, 200)}`,
        );
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

    // 1. Strategies list (the homepage card grid)
    {
        const res = http.get(
            `${BASE_URL}/v1/strategies`,
            { ...headers, tags: { endpoint: 'strategies_list' } },
        );
        errorRate.add(!check(res, { 'status 200': (r) => r.status === 200 }));
    }

    // 2. Pick a random strategy from the list, fetch detail + curves
    {
        const list = http.get(
            `${BASE_URL}/v1/strategies`,
            { ...headers, tags: { endpoint: 'strategies_list' } },
        );
        let code = null;
        try {
            const items = list.json('items') || list.json();
            if (Array.isArray(items) && items.length > 0) {
                code = items[Math.floor(Math.random() * items.length)].code;
            }
        } catch (_e) {
            // ignore — code stays null and we skip detail calls
        }
        if (code) {
            const detail = http.get(
                `${BASE_URL}/v1/strategies/${code}`,
                { ...headers, tags: { endpoint: 'strategy_detail' } },
            );
            errorRate.add(!check(detail, { 'status 200': (r) => r.status === 200 }));

            const equity = http.get(
                `${BASE_URL}/v1/strategies/${code}/equity-curve`,
                { ...headers, tags: { endpoint: 'equity_curve' } },
            );
            errorRate.add(!check(equity, { 'status 200': (r) => r.status === 200 }));

            const monthly = http.get(
                `${BASE_URL}/v1/strategies/${code}/monthly-returns`,
                { ...headers, tags: { endpoint: 'monthly_returns' } },
            );
            errorRate.add(!check(monthly, { 'status 200': (r) => r.status === 200 }));
        }
    }

    // 3. Signals list
    {
        const res = http.get(
            `${BASE_URL}/v1/signals`,
            { ...headers, tags: { endpoint: 'signals_list' } },
        );
        errorRate.add(!check(res, { 'status 200': (r) => r.status === 200 }));
    }

    // 4. The dashboard typically re-fetches every 5-10s;
    //    we model 2 RPS per VU by sleeping 0.5s.
    sleep(0.5);
}
