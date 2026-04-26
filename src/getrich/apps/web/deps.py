"""FastAPI 公共依赖。"""

from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterator
from uuid import uuid4

from fastapi import Depends, Header, Query

from getrich.apps.web.pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    PageParams,
    make_page_params,
)
from getrich.libs.postgres import pg_pool


if TYPE_CHECKING:
    from psycopg import AsyncConnection


async def get_db() -> AsyncIterator[AsyncConnection]:
    """提供一个数据库连接（请求级别），用完自动归还连接池。"""
    async with pg_pool.connection() as conn:
        yield conn


async def get_current_user(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> str | None:
    """开发期 mock 认证：从 X-User-Id 头读取当前用户的 UUID 字符串。

    - 未传头：返回 None（公共接口、列表浏览等仍可访问）
    - 传了头：返回字符串形式的 UUID，下游服务用它写库
    后续接入 JWT 时把这里换成 token 解析即可，路由签名不变。
    """
    return x_user_id


async def require_user(
    user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> str:
    """要求传 X-User-Id；未传则视为未登录返回 401。"""
    if not user_id:
        from getrich.apps.web.errors import Unauthorized
        raise Unauthorized("auth required: please pass X-User-Id header")
    return user_id


async def request_id(x_request_id: str | None = Header(default=None)) -> str:
    """获取或生成本次请求的 request_id。"""
    return x_request_id or uuid4().hex


def page_dep(
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> PageParams:
    return make_page_params(page=page, page_size=page_size)


__all__ = [
    "get_db",
    "get_current_user",
    "require_user",
    "request_id",
    "page_dep",
    "Depends",
]
