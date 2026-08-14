"""HTTP request metrics middleware.

Wraps the FastAPI app and increments
``getrich_http_requests_total`` / observes
``getrich_http_request_duration_seconds`` for every request.

Path-label cardinality
----------------------

A naive ``request.url.path`` label would create one label per
distinct URL — including path parameters (UUIDs, signal codes,
etc.) — and explode Prometheus cardinality within hours. We
mitigate by using ``request.scope.get("route").path`` which is
the route TEMPLATE (e.g. ``/v1/strategies/{code}``), not the
concrete URL. The fallback ``request.url.path`` is used when
the request didn't match a route (404 on an unknown path) and
still creates one label per malformed URL, but only for
malformed traffic and is bounded by the number of unique bad
URLs an attacker can try.
"""

from __future__ import annotations

from time import perf_counter

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from getrich.apps.web.metrics import (
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_TOTAL,
)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Increment the request count + duration histogram on every dispatch.

    The middleware is intentionally cheap: one ``perf_counter()``
    call, two ``labels().inc()`` / ``.observe()`` calls, and one
    attribute lookup for the route template. No body reads, no
    allocations beyond the labels dict.

    Excluded paths: the ``/metrics`` endpoint itself is exempt
    from labeling (otherwise Prometheus's own scrape loop would
    show up in the metric, polluting the rate). The exclusion
    is a simple prefix check; if the path ever becomes a router
    template that doesn't start with ``/metrics``, the prefix
    check still works as long as the URL starts with ``/metrics``.
    """

    _EXCLUDED_PREFIXES: tuple[str, ...] = ("/metrics",)

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        if any(path.startswith(prefix) for prefix in self._EXCLUDED_PREFIXES):
            # Skip the instrumentation on /metrics scrapes so the
            # scrape itself doesn't show up in the rate panel.
            return await call_next(request)

        # Prefer the route TEMPLATE (e.g. ``/v1/strategies/{code}``)
        # over the concrete URL. The route is NOT in ``request.scope``
        # before dispatch — Starlette resolves it during routing,
        # which happens between the middleware and the handler. We
        # therefore read it from the scope AFTER ``call_next``
        # returns; if the request didn't match a route (404 on a
        # typo) the concrete path is used and the cardinality leak
        # is bounded by the number of unique bad URLs.
        method = request.method
        start = perf_counter()
        try:
            response: Response = await call_next(request)
        except Exception:
            # If the downstream app raised (which FastAPI converts
            # to a 500 response), observe the duration and the
            # 500 status, then re-raise. Without this the metric
            # would silently miss 5xx responses raised from inside
            # the route handler.
            duration = perf_counter() - start
            route = request.scope.get("route")
            template_path = getattr(route, "path", None) or path
            HTTP_REQUESTS_TOTAL.labels(method, template_path, "500").inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(method, template_path).observe(duration)
            raise
        route = request.scope.get("route")
        template_path = getattr(route, "path", None) or path
        duration = perf_counter() - start
        HTTP_REQUESTS_TOTAL.labels(method, template_path, str(response.status_code)).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(method, template_path).observe(duration)
        return response
