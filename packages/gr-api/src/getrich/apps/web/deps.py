"""FastAPI 公共依赖。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import Depends, Header, Query, Request

from getrich.apps.web.pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    PageParams,
    make_page_params,
)
from getrich.config import settings
from getrich.libs.postgres import pg_pool


if TYPE_CHECKING:
    from psycopg import AsyncConnection


async def get_db() -> AsyncIterator[AsyncConnection]:
    """提供一个数据库连接（请求级别），用完自动归还连接池。"""
    async with pg_pool.connection() as conn:
        yield conn


# ---------------------------------------------------------------------------
# JWT auth helpers
# ---------------------------------------------------------------------------


def _extract_bearer_token(request: Request) -> str | None:
    """Extract Bearer token from the Authorization header, if present."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


async def get_current_user(request: Request) -> str | None:
    """Try JWT Bearer token first, then fall back to X-User-Id header.

    Returns the user UUID string, or None if unauthenticated.
    """
    # 1) Try JWT Bearer token
    token = _extract_bearer_token(request)
    if token:
        from getrich.apps.web.auth import verify_token
        from getrich.config import settings

        try:
            payload = verify_token(token, settings.web.jwt_secret)
            return payload["sub"]
        # silent-fail-ok: token invalid/expired — fall through to the
        # legacy X-User-Id header so dev mock auth still works.
        # Real auth failures surface as 401 from require_user
        # when no header is present either.
        except ValueError:
            # Token invalid/expired — fall through to legacy header
            pass

    # 2) Fallback: legacy X-User-Id header (dev mock auth)
    x_user_id = request.headers.get("X-User-Id")
    return x_user_id or None


async def require_user(request: Request) -> str:
    """Require valid JWT (or legacy X-User-Id header). Returns user UUID string."""
    user_id = await get_current_user(request)
    if not user_id:
        from getrich.apps.web.errors import Unauthorized

        raise Unauthorized("auth required: please log in")
    return user_id


async def require_admin(
    user_id: str = Depends(require_user),
) -> str:
    """要求当前用户具备后台导入权限。

    开发环境允许已登录用户访问，生产环境必须通过
    ``GETRICH_ADMIN_USER_IDS`` 显式配置管理员用户 ID。
    """
    admin_ids = {
        item.strip() for item in os.getenv("GETRICH_ADMIN_USER_IDS", "").split(",") if item.strip()
    }
    if user_id in admin_ids:
        return user_id
    if settings.is_dev:
        return user_id

    from getrich.apps.web.errors import Forbidden

    raise Forbidden("admin permission required")


async def request_id(x_request_id: str | None = Header(default=None)) -> str:
    """获取或生成本次请求的 request_id。"""
    return x_request_id or uuid4().hex


def page_dep(
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    limit: int | None = Query(None, alias="limit", ge=1, le=MAX_PAGE_SIZE),
) -> PageParams:
    """Pagination dependency.

    Accepts both ``page_size`` (canonical) and ``limit`` (frontend alias used
    by ``frontend/src/api/orders.ts`` and similar modules). When ``limit`` is
    provided, it overrides ``page_size``.
    """
    effective_size = limit if limit is not None else page_size
    return make_page_params(page=page, page_size=effective_size)


__all__ = [
    "get_db",
    "get_current_user",
    "require_user",
    "require_admin",
    "request_id",
    "page_dep",
    "Depends",
]
