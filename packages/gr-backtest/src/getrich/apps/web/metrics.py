"""Prometheus metrics for the GetRich platform.

Defines the live-signal metrics plus a small set of API-level
metrics (request count + duration) that the HTTP
middleware (see ``metrics_middleware``) increments on every
request. All metrics live in the default ``REGISTRY`` and are
exposed at ``GET /metrics`` (no auth, so a Prometheus scraper can
pull without provisioning credentials).

Naming convention
-----------------

All metric names use the ``getrich_`` prefix and snake_case
identifiers. Units are encoded in the suffix where applicable
(``_seconds`` for histograms, ``_total`` for counters — the
Prometheus convention). Histograms use buckets that cover the
expected operating range for a single tick of the live signal
pipeline (sub-millisecond to 30s).

Stability
---------

The metric names and label sets are considered part of the
public contract with the dashboard. Renaming a metric is a
breaking change (Grafana panels reference the old name); a
new metric must be added alongside the old one and the old
one deprecated, not deleted.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest


# ---------------------------------------------------------------------------
# Live-signal metrics (the 5 documented in monitoring.md §6.3)
# ---------------------------------------------------------------------------

# Total wall-clock time for one ``LiveSignalRunner.run_once()`` cycle.
# Buckets span sub-millisecond (no-op tick) to 30s (worst-case
# ClickHouse stall). Anything > 30s is the live pipeline's
# "stalled" alert threshold.
LIVE_RUN_ONCE_SECONDS = Histogram(
    "getrich_live_run_once_seconds",
    "Wall-clock time of one LiveSignalRunner.run_once() cycle",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

# Number of signals successfully written to the PG ``signals`` table.
# Incremented once per row in ``EvalSignalWriter.persist`` (or
# equivalent writer), so a 1-tick cycle with 3 signals = +3.
LIVE_SIGNALS_PERSISTED_TOTAL = Counter(
    "getrich_live_signals_persisted_total",
    "Number of signals successfully persisted to PostgreSQL",
)

# Risk alerts emitted by the LiveRiskMonitor, bucketed by severity
# (info / warning / critical). The alerting policy in monitoring.md
# §5.2 says "critical" alerts must trigger Email + Webhook, so the
# rate of criticals is the most operationally important sub-bucket.
LIVE_ALERTS_EMITTED_TOTAL = Counter(
    "getrich_live_alerts_emitted_total",
    "Number of risk alerts emitted by LiveRiskMonitor, by severity",
    ["severity"],
)

# Granular timing for the 3 load steps inside build_context().
# ``bars`` is the SELECT against md_bars_1m, ``factors`` is the
# SELECT against factors_long, ``account`` is the account state
# loader. A spike in any one bucket is a leading indicator of a
# dependency issue (e.g. ClickHouse slow query).
LIVE_DATA_LOAD_SECONDS = Histogram(
    "getrich_live_data_load_seconds",
    "Time spent loading data for one live tick, by step",
    ["step"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# Strategy.on_bar() exceptions, bucketed by strategy_id. A
# non-zero rate here is a P0 (strategy is silently not running).
# ``strategy_id`` label cardinality is bounded by the number of
# registered strategies (typically < 1000) so this is safe.
LIVE_STRATEGY_ERRORS_TOTAL = Counter(
    "getrich_live_strategy_errors_total",
    "Exceptions raised by Strategy.on_bar(), by strategy_id",
    ["strategy_id"],
)


# ---------------------------------------------------------------------------
# API-level metrics (instrumented by MetricsMiddleware)
# ---------------------------------------------------------------------------

# Request count, labeled by method + route template + status.
# ``path`` is the route template (e.g. ``/v1/strategies/{code}``)
# NOT the raw URL — using the raw URL would create one label
# per UUID and explode Prometheus cardinality.
HTTP_REQUESTS_TOTAL = Counter(
    "getrich_http_requests_total",
    "Total HTTP requests, by method, route template, and status",
    ["method", "path", "status"],
)

# Request duration histogram. Buckets cover sub-millisecond
# (cached /health) to 10s (long-running endpoint). Anything
# above the P99 SLO (500ms, per monitoring.md §6.1) lands in
# the 1s+ buckets and is easy to alert on.
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "getrich_http_request_duration_seconds",
    "HTTP request duration, by method and route template",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


# ---------------------------------------------------------------------------
# /metrics endpoint helper
# ---------------------------------------------------------------------------


def render_metrics() -> tuple[bytes, str]:
    """Render the current registry snapshot for a Prometheus scraper.

    Returns the (body, content_type) tuple suitable for a
    ``Response(body=..., media_type=...)`` return value. Uses
    ``prometheus_client.generate_latest`` (the official text
    exposition format) and the official content type constant
    so Grafana / Prometheus can parse the result without any
    glue code.
    """
    return generate_latest(), CONTENT_TYPE_LATEST


__all__ = [
    "LIVE_RUN_ONCE_SECONDS",
    "LIVE_SIGNALS_PERSISTED_TOTAL",
    "LIVE_ALERTS_EMITTED_TOTAL",
    "LIVE_DATA_LOAD_SECONDS",
    "LIVE_STRATEGY_ERRORS_TOTAL",
    "HTTP_REQUESTS_TOTAL",
    "HTTP_REQUEST_DURATION_SECONDS",
    "render_metrics",
]
