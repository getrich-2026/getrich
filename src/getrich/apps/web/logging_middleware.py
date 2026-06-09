"""Structured logging + request_id propagation.

Why this module exists
----------------------
The web app emits ~6 distinct log lines per request today
(``auth.router`` login, ``backtest_jobs`` create, the SSE
listener, the metrics middleware, etc.). Without a shared
``request_id``, correlating those lines on a 500 / 502 is
guesswork: the user pastes a ``request_id`` from the response
envelope and we grep the log file by it. If only ONE line in
the chain has that id, we lose 5 lines of context.

The fix is two pieces:

1. A ``contextvars.ContextVar`` holding the current request's
   ``request_id``. It's a ``ContextVar`` (not a module-level
   global) so async / SSE generator / BackgroundTasks all
   inherit the value for the duration of their task — without
   it, a background job spawned in the same request scope
   would log without an id and break correlation.
2. A ``RequestIdLogFilter`` that injects the var into every
   ``LogRecord`` so the formatter can render it. The filter
   is installed ONCE at app startup (``main.py``) and lives
   on the root logger, so every existing ``logging.getLogger(
   __name__)`` call in the codebase picks it up without any
   per-module wiring.

The filter is intentionally tolerant: if the var is unset
(e.g. an admin script, a Celery worker, a CLI migration) the
filter writes ``request_id="-"`` instead of raising. That
keeps legacy log calls working in non-FastAPI contexts.

Why not ``structlog``? Two reasons:
  - We already have a ``Logger`` compatibility wrapper in
    ``libs/logging.py`` and 2 services using
    ``logging.getLogger(__name__)``. Swapping to ``structlog``
    is a Round-sized migration. The filter-then-format change
    is ~30 lines and zero per-call-site changes.
  - Production logging pipelines (Loki / CloudWatch / ELK)
    all parse stdlib JSON fine. We get 80% of the value with
    stdlib + a filter.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


# Header name. Lower-case: Starlette / ASGI normalises header
# names to lower-case before they reach us.
_REQUEST_ID_HEADER = "x-request-id"


# A sentinel so the filter never raises on a missing var.
_UNSET = "-"
_current_request_id: ContextVar[str] = ContextVar("getrich_request_id", default=_UNSET)


def get_current_request_id() -> str:
    """Return the request id for the current async context, or ``-``."""
    return _current_request_id.get()


class RequestIdLogFilter(logging.Filter):
    """Inject the per-request id into every ``LogRecord``.

    Installed on the root logger in ``main.create_app()`` so it
    applies to every existing and future ``logging.getLogger()``
    caller without per-module wiring. The filter is fail-safe:
    a missing var produces ``"-"`` rather than a KeyError.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.request_id = _current_request_id.get()
        return True


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Bind the request id from the inbound header (or generate one)
    to a ``ContextVar`` for the duration of the request.

    Order matters in the middleware stack: this MUST be the
    OUTERMOST layer so that downstream errors (including the
    4xx/5xx envelope renderer) all carry the same id. We add
    it BEFORE SecurityHeadersMiddleware in ``main.py``.

    The id is also written to the response header
    ``X-Request-Id`` so the frontend / curl can show / copy it
    for support tickets — mirrors the body's ``request_id``
    field in the JSON envelope.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        # Read the inbound id (or generate a hex uuid4). We can't
        # import the FastAPI ``request_id`` dependency here because
        # that name is the async dep itself (returns a coroutine
        # when called bare). Re-implementing the trivial read +
        # fallback keeps the wiring in this module self-contained.
        rid = request.headers.get(_REQUEST_ID_HEADER) or uuid4().hex
        token = _current_request_id.set(rid)
        try:
            response: Response = await call_next(request)
        finally:
            _current_request_id.reset(token)
        response.headers["X-Request-Id"] = rid
        return response
