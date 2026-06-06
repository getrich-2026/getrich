"""Security middleware for the FastAPI app.

Currently adds:
- ``Content-Security-Policy`` — defense in depth against XSS. If an
  attacker manages to inject script into a stored field (e.g.
  bypassing the bleach + DOMPurify + CHECK layers on
  ``strategies.detail_html``), the browser will refuse to execute
  any inline script under the default policy.
- ``X-Content-Type-Options: nosniff`` — refuses MIME sniffing on
  user-supplied content (e.g. ``detail_html``).
- ``Referrer-Policy: strict-origin-when-cross-origin`` — only the
  origin (not full URL) is sent in cross-origin Referer headers, so
  the strategy_code in ``/strategies/{code}`` doesn't leak to
  third-party CDNs.
- ``X-Frame-Options: DENY`` — anti-clickjacking; we never expect the
  API responses to be framed.

The middleware is intentionally simple: it doesn't read the request
body, doesn't touch the response body, and runs in O(headers) per
request. It's added as the OUTERMOST layer so the headers are set
on EVERY response, including 4xx/5xx error envelopes and the
``/health`` probe.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


# Static headers — these don't depend on request path or env.
_STATIC_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "DENY",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject the standard security response headers on every response.

    Parameters
    ----------
    app : ASGIApp
        The next ASGI app in the stack.
    csp_policy : str
        The Content-Security-Policy header value. Empty string disables
        the header entirely (used in tests that want to assert a
        default-allow behaviour).
    """

    def __init__(self, app: ASGIApp, *, csp_policy: str) -> None:
        super().__init__(app)
        self._csp_policy = csp_policy

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        response: Response = await call_next(request)
        # The static headers go on every response, regardless of CSP
        # config — they're cheap, harmless, and address well-known
        # attack classes (sniffing, framing, referrer leakage).
        for header, value in _STATIC_SECURITY_HEADERS.items():
            response.headers[header] = value
        if self._csp_policy:
            response.headers["Content-Security-Policy"] = self._csp_policy
        return response
