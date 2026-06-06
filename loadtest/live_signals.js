// live_signals.js — read + mark-read traffic for the live
// signal panel.
//
// Purpose:
//   Simulate a "live dashboard" user: the panel polls
//   /v1/signals every 3 seconds and POSTs /read when the
//   user clicks a row. We hammer both paths to make sure
//   the pg_notify / SSE bridge (Round #1063) doesn't
//   bottleneck under load.
//
// Why this matters:
//   In Round #1080 the worker cancel LISTEN channel was
//   added, and the live signal feed uses the same pg_notify
//   pipe. A regression in the listener would surface here
//   as a 5xx storm on /signals/{id}/read.
//
// SLO:
//   - p95 list latency < 250 ms (the list endpoint is
//     small and cached at the DB layer)
//   - p95 mark-read latency < 200 ms (single UPDATE)
//   - error rate < 0.5 % (mark-read is idempotent, so 0.5%
//     5xx is a real problem)
//
// Run:
//   k6 run loadtest/live_signals.js

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate } from 'k6/metrics';

const marksRead = new Counter('signals_marked_read');
const errorRate = new Rate('errors');

export const options = {
    // 30 VUs, each polling every 3s. 30 / 3 = 10 RPS.
    vus: __ENV.K6_VUS ? parseInt(__ENV.K6_VUS, 10) : 30,
    duration: __ENV.K6_DURATION || '3m',

    thresholds: {
        'http_req_duration{endpoint:list}': ['p(95)<250'],
        'http_req_duration{endpoint:unread_summary}': ['p(95)<200'],
        'http_req_duration{endpoint:mark_read}': ['p(95)<200'],
        'errors': ['rate<0.005'],
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

    // 1. Polling: list (paginated, default 50)
    {
        const res = http.get(
            `${BASE_URL}/v1/signals?limit=50`,
            { ...headers, tags: { endpoint: 'list' } },
        );
        const ok = check(res, { 'status 200': (r) => r.status === 200 });
        errorRate.add(!ok);
    }

    // 2. Unread summary (drives the badge counter in the navbar)
    {
        const res = http.get(
            `${BASE_URL}/v1/signals/unread-summary`,
            { ...headers, tags: { endpoint: 'unread_summary' } },
        );
        const ok = check(res, { 'status 200': (r) => r.status === 200 });
        errorRate.add(!ok);
    }

    // 3. Mark-read: pick the first unread signal and POST /read.
    //    60% of iterations do this (model the user clicking rows);
    //    the other 40% just poll.
    if (Math.random() < 0.6) {
        const list = http.get(
            `${BASE_URL}/v1/signals?limit=10&is_read=false`,
            { ...headers, tags: { endpoint: 'list' } },
        );
        let code = null;
        try {
            const items = list.json('items') || list.json();
            if (Array.isArray(items) && items.length > 0) {
                code = items[0].code;
            }
        } catch (_e) {
            // ignore
        }
        if (code) {
            const markRes = http.post(
                `${BASE_URL}/v1/signals/${code}/read`,
                '{}',
                { ...headers, tags: { endpoint: 'mark_read' } },
            );
            const ok = check(markRes, {
                'mark_read status 200': (r) => r.status === 200,
            });
            errorRate.add(!ok);
            if (ok) {
                marksRead.add(1);
            }
        }
    }

    // The dashboard polls every 3s.
    sleep(3);
}
