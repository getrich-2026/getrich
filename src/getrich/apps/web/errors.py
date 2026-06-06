"""业务异常类。在路由/服务层抛出，由 response.py 中的 handler 统一包装。"""

from __future__ import annotations


class ApiError(Exception):
    """业务异常基类。"""

    http_status: int = 400
    code: int = 1000

    def __init__(self, message: str, *, code: int | None = None, http_status: int | None = None):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status


class NotFound(ApiError):  # noqa: N818
    http_status = 404
    code = 4040


class BadRequest(ApiError):  # noqa: N818
    http_status = 400
    code = 4000


class Forbidden(ApiError):  # noqa: N818
    http_status = 403
    code = 4030


class Unauthorized(ApiError):  # noqa: N818
    http_status = 401
    code = 4010


class Conflict(ApiError):  # noqa: N818
    http_status = 409
    code = 4090
