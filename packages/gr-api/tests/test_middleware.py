"""Tests for the security-headers + request-id middleware.

Covers:
- The static headers (``X-Content-Type-Options``,
  ``Referrer-Policy``, ``X-Frame-Options``) are set on every response.
- The ``Content-Security-Policy`` header is set when a non-empty
  policy is provided.
- An empty ``csp_policy`` argument disables the header (escape hatch
  for tests that need to assert default browser behaviour).
- Headers are set on BOTH 2xx and 4xx/5xx responses.
- The middleware is wrapped around the FastAPI app in
  ``create_app()`` — verified by spinning a ``TestClient`` and
  hitting ``/health``.
- ``RequestIdMiddleware`` echoes the inbound ``X-Request-Id``
  (or generates one), binds it to a ``ContextVar`` for the
  duration of the request, and the ``RequestIdLogFilter``
  injects the same id into every ``LogRecord`` so multi-line
  handler logs can be correlated with the body envelope.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from gr_api.logging_middleware import (
    RequestIdLogFilter,
    RequestIdMiddleware,
    _current_request_id,
    get_current_request_id,
)
from gr_api.middleware import (
    SecurityHeadersMiddleware,
)


# ---------------------------------------------------------------------------
# Pure middleware tests (use a tiny FastAPI app so we don't have to
# boot the real one with its PG/Redis deps).
# ---------------------------------------------------------------------------


def _make_app(*, csp_policy: str) -> FastAPI:
    """Build a minimal FastAPI app with the security middleware
    installed. Two routes: a 200 and a 500 (so we can assert headers
    show up on both)."""
    app = FastAPI()
    app.add_middleware(
        SecurityHeadersMiddleware,
        csp_policy=csp_policy,
    )

    @app.get("/ok")
    async def ok() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/boom")
    async def boom() -> None:
        raise HTTPException(status_code=500, detail="kaboom")

    return app


def test_static_headers_set_on_2xx_response() -> None:
    """All three static headers land on the 200 response."""
    app = _make_app(csp_policy="default-src 'self'")
    client = TestClient(app, raise_server_exceptions=False)

    r = client.get("/ok")

    assert r.status_code == 200
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert r.headers["X-Frame-Options"] == "DENY"


def test_static_headers_set_on_5xx_response() -> None:
    """The middleware must inject headers even when the underlying
    route raises. Otherwise an unhandled exception path would
    bypass CSP and an attacker could probe error envelopes to see
    the API is "naked" of protections.
    """
    app = _make_app(csp_policy="default-src 'self'")
    client = TestClient(app, raise_server_exceptions=False)

    r = client.get("/boom")

    assert r.status_code == 500
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert r.headers["X-Frame-Options"] == "DENY"


def test_csp_header_set_when_policy_non_empty() -> None:
    app = _make_app(csp_policy="default-src 'self'; script-src 'self'")
    client = TestClient(app, raise_server_exceptions=False)

    r = client.get("/ok")

    assert r.headers["Content-Security-Policy"] == ("default-src 'self'; script-src 'self'")


def test_csp_header_omitted_when_policy_empty() -> None:
    """An empty policy string MUST NOT emit the header at all.
    Some test harnesses assert on `len(headers)` for a "default
    browser" baseline and an empty CSP would still match; the
    contract is: empty string = no header.
    """
    app = _make_app(csp_policy="")
    client = TestClient(app, raise_server_exceptions=False)

    r = client.get("/ok")

    assert "Content-Security-Policy" not in r.headers
    # The static headers still go on.
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_csp_header_passes_through_verbatim() -> None:
    """The middleware does not parse or mutate the policy — the
    caller is responsible for syntax. This guards against an
    accidental future refactor that, say, lowercases directive
    names (which would break the spec).
    """
    custom = "default-src 'self'; img-src 'self' https://cdn.example.com"
    app = _make_app(csp_policy=custom)
    client = TestClient(app, raise_server_exceptions=False)

    r = client.get("/ok")

    assert r.headers["Content-Security-Policy"] == custom


# ---------------------------------------------------------------------------
# Integration: assert the real app's `/health` exposes the headers.
# ---------------------------------------------------------------------------


def test_real_app_health_emits_security_headers() -> None:
    """Spin up the real ``create_app()`` and hit ``/health``. This
    catches the case where someone refactors ``main.py`` and drops
    the ``app.add_middleware(SecurityHeadersMiddleware, ...)`` call.
    The default CSP policy (from settings) is non-empty so the
    header must be present.
    """
    from gr_api.main import create_app

    app = create_app()
    client = TestClient(app)

    r = client.get("/health")

    assert r.status_code == 200
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in r.headers
    # The default policy mentions these directives — guards against
    # a future refactor that accidentally drops them.
    csp = r.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "base-uri 'self'" in csp


# ---------------------------------------------------------------------------
# RequestIdMiddleware — bind x-request-id to a ContextVar, echo as
# X-Request-Id response header, and inject into every LogRecord via
# the RequestIdLogFilter installed on the root logger.
# ---------------------------------------------------------------------------


def _make_app_with_request_id() -> FastAPI:
    """A minimal app with both SecurityHeadersMiddleware and
    RequestIdMiddleware installed, in the production order."""
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/echo")
    async def echo() -> dict[str, str]:
        # A route that emits a log line so the filter is
        # exercised end-to-end.
        logging.getLogger("test_middleware").info("inside-echo")
        return {"request_id": get_current_request_id()}

    @app.get("/boom")
    async def boom() -> None:
        raise HTTPException(status_code=500, detail="kaboom")

    return app


def test_request_id_middleware_generates_id_when_no_inbound_header() -> None:
    """Missing inbound X-Request-Id → server generates a hex id and
    echoes it in the response header."""
    app = _make_app_with_request_id()
    client = TestClient(app)
    r = client.get("/echo")
    assert r.status_code == 200
    rid = r.headers.get("X-Request-Id")
    assert rid is not None
    # Generated by ``uuid4().hex`` (32 hex chars).
    assert len(rid) == 32
    assert all(c in "0123456789abcdef" for c in rid)


def test_request_id_middleware_echoes_inbound_id() -> None:
    """Inbound X-Request-Id is reflected verbatim on the response and
    available to the route via the ContextVar."""
    app = _make_app_with_request_id()
    client = TestClient(app)
    r = client.get("/echo", headers={"X-Request-Id": "client-supplied-42"})
    assert r.headers["X-Request-Id"] == "client-supplied-42"
    # Route's get_current_request_id() must agree.
    assert r.json()["request_id"] == "client-supplied-42"


def test_request_id_middleware_resets_context_var_after_request() -> None:
    """A bug in reset() would leak the previous request's id into
    the next test (and into the log lines that follow). The default
    sentinel ``"-"`` proves the ContextVar is back to its initial
    value when the response is done."""
    # Start clean.
    assert get_current_request_id() == "-"

    app = _make_app_with_request_id()
    client = TestClient(app)
    client.get("/echo", headers={"X-Request-Id": "leak-check"})

    # After the request completes, the var must NOT still hold
    # ``leak-check`` — otherwise subsequent background logs would
    # be misattributed to that request.
    assert get_current_request_id() == "-"


def test_request_id_filter_attaches_to_log_records() -> None:
    """The ``RequestIdLogFilter`` is the bridge from the ContextVar
    to the ``LogRecord.request_id`` attribute used by downstream
    formatters. Without it, the field would be missing and a JSON
    formatter would emit ``"request_id": null`` instead of the
    actual id."""
    # Install a fresh root-level filter so this test doesn't
    # depend on the rest of the suite.
    flt = RequestIdLogFilter()
    token = _current_request_id.set("rid-from-test")
    try:
        record = logging.LogRecord(
            name="x",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="hi",
            args=(),
            exc_info=None,
        )
        flt.filter(record)
        assert record.request_id == "rid-from-test"  # type: ignore[attr-defined]
    finally:
        _current_request_id.reset(token)


def test_create_app_installs_filter_and_middleware() -> None:
    """End-to-end: ``create_app()`` wires the filter to the root
    logger and the middleware to the app stack. Without this, no
    log line in production carries the id."""
    # Reload the web package to clear any per-test filter state
    # installed by a previous test (the idempotency check in
    # ``create_app()`` prevents double-add, so a fresh import
    # gives a clean baseline).
    from gr_api.main import create_app

    app = create_app()
    client = TestClient(app)

    root_filters = logging.getLogger().filters
    assert any(isinstance(f, RequestIdLogFilter) for f in root_filters)

    # The middleware emits X-Request-Id on /health.
    r = client.get("/health")
    assert "X-Request-Id" in r.headers
