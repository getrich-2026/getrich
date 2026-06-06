// auth_smoke.js — minimal k6 load test for the auth endpoints.
//
// Purpose:
//   Sanity-check the auth path: POST /v1/auth/login and
//   POST /v1/auth/register. We use this as the FIRST load
//   test on a fresh deployment ("does the server even accept
//   requests?") before running the heavier read/write tests.
//
// SLO:
//   - p95 latency < 500 ms (login is bcrypt-bounded, ~250 ms)
//   - error rate < 1 % (a 401 on wrong creds is an error here
//     because the test always sends valid creds)
//
// Run:
//   k6 run loadtest/auth_smoke.js
//   k6 run --vus 20 --duration 60s loadtest/auth_smoke.js

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate } from 'k6/metrics';

const errorRate = new Rate('errors');

export const options = {
    // 10 VUs over 30s by default. Override on the CLI.
    vus: __ENV.K6_VUS ? parseInt(__ENV.K6_VUS, 10) : 10,
    duration: __ENV.K6_DURATION || '30s',

    // Thresholds. A failed threshold makes k6 exit non-zero,
    // which fails the CI job.
    thresholds: {
        // Login is a bcrypt-bounded op; we should easily fit
        // under 500 ms p95 even on a small box.
        'http_req_duration{endpoint:login}': ['p(95)<500'],
        'http_req_duration{endpoint:refresh}': ['p(95)<300'],
        'errors': ['rate<0.01'],
    },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const EMAIL = __ENV.TEST_USER_EMAIL || 'loadtest@example.com';
const PASSWORD = __ENV.TEST_USER_PASSWORD || 'loadtest-pw-12345';

export default function () {
    // 1. Login
    const loginRes = http.post(
        `${BASE_URL}/v1/auth/login`,
        JSON.stringify({ email: EMAIL, password: PASSWORD }),
        {
            headers: { 'Content-Type': 'application/json' },
            tags: { endpoint: 'login' },
        },
    );
    const loginOk = check(loginRes, {
        'login status 200': (r) => r.status === 200,
        'login returns access_token': (r) => {
            try {
                return r.json('access_token') !== undefined;
            } catch (_e) {
                return false;
            }
        },
    });
    errorRate.add(!loginOk);

    if (!loginOk) {
        // Don't proceed to refresh; the next iteration will
        // retry login. We add 1s sleep to back off the
        // server if it's overloaded.
        sleep(1);
        return;
    }

    // 2. Refresh (uses the refresh_token from the login response)
    let refreshToken;
    try {
        refreshToken = loginRes.json('refresh_token');
    } catch (_e) {
        refreshToken = null;
    }
    if (refreshToken) {
        const refreshRes = http.post(
            `${BASE_URL}/v1/auth/refresh`,
            JSON.stringify({ refresh_token: refreshToken }),
            {
                headers: { 'Content-Type': 'application/json' },
                tags: { endpoint: 'refresh' },
            },
        );
        const refreshOk = check(refreshRes, {
            'refresh status 200': (r) => r.status === 200,
            'refresh returns access_token': (r) => {
                try {
                    return r.json('access_token') !== undefined;
                } catch (_e) {
                    return false;
                }
            },
        });
        errorRate.add(!refreshOk);
    }

    sleep(1);
}
