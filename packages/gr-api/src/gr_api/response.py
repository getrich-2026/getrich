"""统一响应包装：{code, message, data, timestamp, request_id}。"""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse
from gr_api.errors import ApiError
from gr_api.logging_middleware import _current_request_id, get_current_request_id
from gr_api.middleware import _STATIC_SECURITY_HEADERS


logger = logging.getLogger(__name__)


def _now_ts() -> int:
    return int(time.time())


def success(data: Any, request_id: str, message: str = "success") -> dict[str, Any]:
    """构造成功响应体。"""
    return {
        "code": 0,
        "message": message,
        "data": data,
        "timestamp": _now_ts(),
        "request_id": request_id,
    }


def error_payload(code: int, message: str, request_id: str) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "data": None,
        "timestamp": _now_ts(),
        "request_id": request_id,
    }


def _request_id(request: Request) -> str:
    current = get_current_request_id()
    if current and current != "-":
        return current
    state_rid = getattr(request.state, "request_id", None)
    if isinstance(state_rid, str) and state_rid:
        return state_rid
    rid = request.headers.get("x-request-id")
    return rid or uuid4().hex


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器，所有响应都包装成 ApiResponse 形状。"""

    @app.exception_handler(ApiError)
    async def _handle_api_error(request: Request, exc: ApiError) -> ORJSONResponse:
        return ORJSONResponse(
            status_code=exc.http_status,
            content=error_payload(exc.code, exc.message, _request_id(request)),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> ORJSONResponse:
        # 取首个错误的可读信息
        errs = exc.errors()
        if errs:
            loc = ".".join(str(p) for p in errs[0].get("loc", ()))
            msg = f"{loc}: {errs[0].get('msg', 'invalid')}"
        else:
            msg = "validation failed"
        return ORJSONResponse(
            status_code=422,
            content=error_payload(4220, msg, _request_id(request)),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> ORJSONResponse:
        # ServerErrorMiddleware 位于 RequestIdMiddleware 与 SecurityHeadersMiddleware 外层；
        # 显式补齐 request_id 日志上下文、X-Request-Id 与安全响应头，并在非 dev 环境隐藏异常细节。
        rid = _request_id(request)
        token = _current_request_id.set(rid) if get_current_request_id() == "-" else None
        try:
            logger.exception(
                "Unhandled exception on %s %s (request_id=%s)",
                request.method,
                request.url.path,
                rid,
            )
        finally:
            if token is not None:
                _current_request_id.reset(token)

        settings = getattr(request.app.state, "settings", None)
        is_dev = getattr(settings, "is_dev", True)
        msg = f"internal error: {exc}" if is_dev else "internal server error"
        headers: dict[str, str] = {"X-Request-Id": rid, **_STATIC_SECURITY_HEADERS}
        csp_policy = getattr(getattr(settings, "web", None), "csp_policy", "")
        if csp_policy:
            headers["Content-Security-Policy"] = csp_policy
        return ORJSONResponse(
            status_code=500,
            content=error_payload(5000, msg, rid),
            headers=headers,
        )
