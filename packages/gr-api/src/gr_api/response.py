"""统一响应包装：{code, message, data, timestamp, request_id}。"""

from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse
from gr_api.errors import ApiError


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
        # 未捕获异常 → 5000
        return ORJSONResponse(
            status_code=500,
            content=error_payload(5000, f"internal error: {exc}", _request_id(request)),
        )
