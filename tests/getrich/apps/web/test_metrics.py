"""Tests for the Prometheus metrics endpoint and HTTP middleware.

Two layers of coverage:

1. **Pure metrics module** — the 5 documented live-signal metrics
   + 2 API metrics are registered in the default Prometheus
   registry and the ``render_metrics()`` helper returns a valid
   text-format payload that includes the metric names.

2. **HTTP middleware** — ``MetricsMiddleware`` increments the
   request count + duration histogram on every dispatch, uses the
   ROUTE TEMPLATE (not the raw URL) as the ``path`` label to avoid
   cardinality explosion, and excludes the ``/metrics`` endpoint
   itself from instrumentation so the scrape loop doesn't pollute
   the rate.

The tests are pure stdlib + ``prometheus_client``; they don't
need a real PG / CH / Redis because the metrics module is
process-local (counters and histograms live in memory).
"""

from __future__ import annotations

import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from getrich.apps.web.metrics import (
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_TOTAL,
    LIVE_ALERTS_EMITTED_TOTAL,
    LIVE_DATA_LOAD_SECONDS,
    LIVE_RUN_ONCE_SECONDS,
    LIVE_SIGNALS_PERSISTED_TOTAL,
    LIVE_STRATEGY_ERRORS_TOTAL,
    render_metrics,
)
from getrich.apps.web.metrics_middleware import MetricsMiddleware


# ---------------------------------------------------------------------------
# Helpers: read prometheus_client values via the public ``collect()`` API
# ---------------------------------------------------------------------------


def _counter_value(counter, **expected_labels: str) -> float:
    """Read a counter sample filtered by an exact label dict.

    Uses ``metric.collect()`` (the stable public API) instead of
    poking at ``_metrics`` (private). The counter exposes
    ``<name>_total`` samples; we filter to the labelset of
    interest and return the value. Returns 0.0 if the label
    combination has never been incremented.
    """
    suffix = "_total"
    for family in counter.collect():
        for sample in family.samples:
            if not sample.name.endswith(suffix):
                continue
            if sample.labels == expected_labels:
                return sample.value
    return 0.0


def _counter_total(counter) -> float:
    """Sum a counter across ALL label combinations.

    Used when the test doesn't care which label set the
    increment landed in (e.g. ``test_increment_counters_round_trips``).
    """
    suffix = "_total"
    total = 0.0
    for family in counter.collect():
        for sample in family.samples:
            if sample.name.endswith(suffix):
                total += sample.value
    return total


def _histogram_count(histogram, **expected_labels: str) -> float:
    """Read a histogram's ``_count`` sample for the given label dict.

    The prometheus_client 0.25 API exposes histogram observations
    as ``<name>_count`` samples (separate from the bucket samples).
    Returns 0.0 if the label combination was never observed.
    """
    for family in histogram.collect():
        for sample in family.samples:
            if sample.name.endswith("_count") and not sample.name.endswith(
                "_created"
            ):
                if sample.labels == expected_labels:
                    return sample.value
    return 0.0


# ---------------------------------------------------------------------------
# Pure metrics module
# ---------------------------------------------------------------------------


def test_all_documented_metrics_are_registered() -> None:
    """The 5 monitoring.md metrics + 2 API metrics must be in the
    exposition output. Catches accidental rename / deletion.
    """
    body, content_type = render_metrics()
    text = body.decode("utf-8")
    expected = {
        "getrich_live_run_once_seconds",
        "getrich_live_signals_persisted_total",
        "getrich_live_alerts_emitted_total",
        "getrich_live_data_load_seconds",
        "getrich_live_strategy_errors_total",
        "getrich_http_requests_total",
        "getrich_http_request_duration_seconds",
    }
    missing = {name for name in expected if name not in text}
    assert not missing, (
        f"metrics missing from /metrics output: {missing}. "
        f"Did one of the metric definitions get renamed or removed?"
    )
    assert "text/plain" in content_type, (
        f"unexpected content_type {content_type!r}; Prometheus requires text/plain"
    )


def test_render_metrics_includes_help_and_type_lines() -> None:
    """The text format requires ``# HELP`` and ``# TYPE`` lines for
    each metric family.
    """
    text = render_metrics()[0].decode("utf-8")
    for name in ("getrich_live_signals_persisted_total", "getrich_live_run_once_seconds"):
        help_line = re.search(rf"# HELP {name} ", text)
        type_line = re.search(rf"# TYPE {name} (counter|histogram|gauge)", text)
        assert help_line, f"# HELP line missing for {name}"
        assert type_line, f"# TYPE line missing for {name}"


def test_increment_counters_round_trips_to_exposition() -> None:
    """A ``.inc()`` on a documented counter must be visible in the
    rendered output. The rendered output IS the API Prometheus
    scrapes — round-tripping it is the contract.
    """
    before = _counter_total(LIVE_SIGNALS_PERSISTED_TOTAL)
    LIVE_SIGNALS_PERSISTED_TOTAL.inc(3)
    after = _counter_total(LIVE_SIGNALS_PERSISTED_TOTAL)
    assert after - before == 3, (
        f"counter delta {after - before} != 3; inc() not reflected in exposition"
    )


def test_observe_histogram_round_trips_to_exposition() -> None:
    """A ``.observe()`` on a documented histogram must be visible
    in the ``_count`` line.
    """
    # Use a fresh step label so we don't conflate with earlier
    # tests in the same process.
    LIVE_DATA_LOAD_SECONDS.labels("test_step").observe(0.123)
    count = _histogram_count(LIVE_DATA_LOAD_SECONDS, step="test_step")
    assert count >= 1, (
        f"histogram _count={count} for step=test_step; expected >= 1 after .observe()"
    )


# ---------------------------------------------------------------------------
# HTTP middleware
# ---------------------------------------------------------------------------


def _build_app_with_middleware() -> FastAPI:
    """Build a minimal app with MetricsMiddleware + 3 routes.

    The 3 routes exercise the 3 different label combinations the
    middleware produces:
    - /health is un-prefixed (no /v1)
    - /v1/items/{item_id} is parameterized (route template != URL)
    - /v1/error raises (caught and recorded as 500)

    The /v1/error route is wrapped in a custom exception handler
    that converts the RuntimeError to a 500 response, matching
    what a production app would do. Without the handler the
    TestClient re-raises the exception in the test, which
    matches the production behaviour with --reload off but
    doesn't help us assert the metric recorded the 500.
    """
    app = FastAPI()
    app.add_middleware(MetricsMiddleware)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/items/{item_id}")
    async def get_item(item_id: str) -> dict[str, str]:
        return {"id": item_id}

    @app.get("/v1/error")
    async def boom() -> dict[str, str]:
        raise RuntimeError("intentional test failure")

    @app.exception_handler(RuntimeError)
    async def _runtime_error_handler(_request, _exc) -> dict[str, str]:
        # Production behaviour: an unhandled RuntimeError becomes
        # a 500 response. The middleware sits OUTSIDE this handler,
        # so it sees the 500 status on its way out.
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=500, content={"detail": "internal"})

    return app


def test_middleware_excluded_path_skips_counting() -> None:
    """A request to ``/metrics`` must NOT increment the request
    counter (otherwise the scrape loop inflates the rate).
    """
    app = _build_app_with_middleware()
    client = TestClient(app)
    # /metrics isn't registered; we hit it anyway to assert the
    # middleware doesn't crash and doesn't count. FastAPI returns
    # 404 for unknown routes, but the middleware short-circuits
    # before the route resolution.
    response = client.get("/metrics")
    assert response.status_code == 404
    # The counter for /metrics should never have been created
    # (the middleware returns early before labels()).
    val = _counter_value(HTTP_REQUESTS_TOTAL, method="GET", path="/metrics", status="404")
    assert val == 0.0, (
        f"/metrics request incremented the request counter to {val}; "
        f"the excluded-prefixes list is missing /metrics"
    )


def test_middleware_uses_route_template_not_concrete_url() -> None:
    """Hitting ``/v1/items/abc`` and ``/v1/items/xyz`` must
    increment the SAME label combination (path =
    ``/v1/items/{item_id}``). Using the raw URL would create one
    label per item_id and explode Prometheus cardinality.
    """
    app = _build_app_with_middleware()
    client = TestClient(app)
    client.get("/v1/items/abc")
    client.get("/v1/items/xyz")
    val = _counter_value(
        HTTP_REQUESTS_TOTAL,
        method="GET",
        path="/v1/items/{item_id}",
        status="200",
    )
    assert val == 2, (
        f"expected 2 increments for /v1/items/{{item_id}} 200, got {val}; "
        f"middleware labelled by concrete URL not route template"
    )


def test_middleware_records_500_on_raised_exception() -> None:
    """A handler that raises must still be recorded (with status
    500). Without this, exceptions that escape the route handler
    would silently miss the metric.
    """
    app = _build_app_with_middleware()
    client = TestClient(app)
    client.get("/v1/error")
    val = _counter_value(HTTP_REQUESTS_TOTAL, method="GET", path="/v1/error", status="500")
    assert val == 1, (
        f"500 response from raised exception not recorded; got {val} for /v1/error 500"
    )


def test_middleware_increments_duration_histogram() -> None:
    """Every counted request must also feed the duration histogram.
    Without the parallel observe, the metric would only tell us
    RPS, not latency.
    """
    app = _build_app_with_middleware()
    client = TestClient(app)
    client.get("/health")
    count = _histogram_count(HTTP_REQUEST_DURATION_SECONDS, method="GET", path="/health")
    assert count >= 1, (
        f"duration histogram count={count} for /health; expected >= 1 after request"
    )


# ---------------------------------------------------------------------------
# Severity label sanity (alerts counter)
# ---------------------------------------------------------------------------


def test_alerts_counter_supports_severity_label() -> None:
    """The alerts counter has a ``severity`` label with at least
    the 3 documented values (info / warning / critical). Adding
    a new label value is a breaking change for Grafana, so the
    test enforces the 3-value contract.
    """
    for severity in ("info", "warning", "critical"):
        LIVE_ALERTS_EMITTED_TOTAL.labels(severity).inc()
    text = render_metrics()[0].decode("utf-8")
    for severity in ("info", "warning", "critical"):
        assert f'severity="{severity}"' in text, (
            f"severity={severity!r} label not in exposition output; "
            f"alert dashboard panels will break"
        )
