"""Tests for the security-headers middleware.

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
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from getrich.apps.web.middleware import (
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
    from getrich.apps.web.main import create_app

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
