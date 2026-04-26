"""FastAPI 应用入口。

启动方式：
    uvicorn getrich.apps.web.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from getrich.apps.web.response import register_exception_handlers
from getrich.apps.web.routers import (
    payments as payments_router,
    signal_settings as signal_settings_router,
    signals as signals_router,
    strategies as strategies_router,
    subscriptions as subscriptions_router,
    user as user_router,
)
from getrich.config import settings
from getrich.libs.postgres import pg_pool


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """初始化与释放 PG 连接池。"""
    await pg_pool.init()
    try:
        yield
    finally:
        await pg_pool.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="GetRich API",
        version="1.1.0",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.web.cors_origins) or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(strategies_router.router, prefix="/v1")
    app.include_router(signals_router.router, prefix="/v1")
    app.include_router(subscriptions_router.router, prefix="/v1")
    app.include_router(signal_settings_router.router, prefix="/v1")
    app.include_router(user_router.router, prefix="/v1")
    app.include_router(payments_router.router, prefix="/v1")

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
