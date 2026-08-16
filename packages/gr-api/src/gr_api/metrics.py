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
    "HTTP_REQUESTS_TOTAL",
    "HTTP_REQUEST_DURATION_SECONDS",
    "render_metrics",
]
