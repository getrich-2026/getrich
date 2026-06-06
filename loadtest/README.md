# Load testing scripts (k6)

This directory contains [k6](https://k6.io) load-test scripts for
the GetRich web API. The tests are organized by traffic class:

| File | Traffic class | Auth | Purpose |
|---|---|---|---|
| `auth_smoke.js` | Login/register | none | Smoke test the auth endpoints; smoke baseline before heavier runs |
| `read_traffic.js` | Read-heavy browsing | yes | `GET /strategies`, `GET /signals`, `GET /equity-curve` — typical dashboard load |
| `backtest_submit.js` | Mixed read + job submit | yes | Submit backtest jobs, poll status, check cancellation rate |
| `live_signals.js` | Read + mark-read | yes | `GET /signals` (live mode) + `POST /signals/{id}/read` burst |

## Running

```bash
# Install k6
brew install k6          # macOS
sudo apt install k6      # Debian / Ubuntu
winget install k6        # Windows (scoop users: scoop install k6)

# Smoke run (10 VUs, 30s, no auth required) — good for CI
k6 run --vus 10 --duration 30s loadtest/auth_smoke.js

# Against a real deployment
BASE_URL=https://staging.getrich.example.com \
TEST_USER_EMAIL=stress@example.com \
TEST_USER_PASSWORD=stresspw123 \
k6 run loadtest/read_traffic.js

# Backtest submit: 5 VUs for 2 minutes, ramped
k6 run --vus 5 --duration 2m loadtest/backtest_submit.js
```

## Environment variables

| Var | Default | Notes |
|---|---|---|
| `BASE_URL` | `http://localhost:8000` | API root |
| `TEST_USER_EMAIL` | — | Required for authenticated scripts |
| `TEST_USER_PASSWORD` | — | Required for authenticated scripts |
| `K6_VUS` | script default | Override VU count |
| `K6_DURATION` | script default | Override duration |

## Thresholds (k6 native)

The scripts set their own `thresholds` block so a CI run that
exceeds the SLO fails automatically. We pick the thresholds
based on the SLOs in `docs/operations/monitoring.md`:

- p95 latency under 300 ms for read endpoints
- p99 latency under 800 ms for backtest submit
- Error rate under 1 % for read, under 0.1 % for auth

## CI integration

A dedicated `.github/workflows/loadtest.yml` (see Round #1162
follow-up) runs `auth_smoke.js` against the staging API on
every push to `main` / `dev`. The heavier scripts are run
manually by SREs during capacity planning or after a perf
regression.
