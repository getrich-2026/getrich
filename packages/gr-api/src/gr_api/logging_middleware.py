"""HTTP 请求上下文与日志 filter。

API lifespan 将 filter 安装到日志输出 handler；挂在 root logger 的 filter
不会处理子 logger 传播来的记录。ContextVar 隔离并发请求，非请求日志使用占位符。
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
    """向输出 handler 收到的记录注入当前 request_id。"""

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
