"""FastAPI 应用入口。

启动方式：
    uvicorn gr_api.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import AsyncIterator


# Round #1204 (Tier 1): psycopg3 (async driver) is incompatible with the
# default ``ProactorEventLoop`` on Windows — uvicorn on Win uses
# Proactor by default, and the moment we touch ``pg_pool.init()`` in
# the FastAPI lifespan we get a noisy "Psycopg cannot use the
# ProactorEventLoop to run in async mode" stack trace. Linux + macOS
# are unaffected (they default to SelectorEventLoop already).
#
# The fix is platform-scoped — DO NOT touch the policy on POSIX. We
# register SelectorEventLoop only on Windows, and we do it at module
# import time so it wins regardless of who starts the event loop
# (uvicorn, pytest-asyncio, the celery worker, etc.).
#
# Verified against the actual error:
#   error connecting in 'pool-1': Psycopg cannot use the
#   'ProactorEventLoop' to run in async mode. Please use a compatible
#   event loop, for instance by running
#   'asyncio.run(..., loop_factory=asyncio.SelectorEventLoop(
#       selectors.SelectSelector()))'
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse, Response
from gr_api.logging_middleware import (
    RequestIdLogFilter,
    RequestIdMiddleware,
)
from gr_api.metrics import render_metrics
from gr_api.metrics_middleware import MetricsMiddleware
from gr_api.middleware import SecurityHeadersMiddleware
from gr_api.response import register_exception_handlers
from gr_api.routers import (
    admin_imports as admin_imports_router,
    auth as auth_router,
    backtest_jobs as backtest_jobs_router,
    backtest_runs as backtest_runs_router,
    backtest_sweeps as backtest_sweeps_router,
    backtest_walk_forwards as backtest_walk_forwards_router,
    diagnosis as diagnosis_router,
    payments as payments_router,
    picks as picks_router,
    signal_settings as signal_settings_router,
    signals as signals_router,
    strategies as strategies_router,
    subscriptions as subscriptions_router,
    user as user_router,
)
from gr_api.services import (
    backtest_job as job_svc,
    backtest_sweep as sweep_svc,
    backtest_walk_forward as wf_svc,
)
from gr_api.services.job_listener import BacktestJobListener
from gr_data.config import settings
from gr_data.db import pg_pool


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize the PG pool, start the LISTEN pump, serve, then tear down.

    Order matters: ``pg_pool.init()`` must come first (the listener
    is configured against the same DSN but opens its own dedicated
    connection; it does not borrow from the pool). ``pg_pool.close()``
    must come last so the listener's ``stop()`` can still touch its
    conn during shutdown.

    The listener is wired into the 3 SSE service modules so the
    ``stream_*_events`` generators can ``subscribe(job_id)`` and
    wake up within ~10ms of a worker-side ``pg_notify`` instead of
    waiting up to ``POLL_INTERVAL_S`` (1s) for the next poll tick.

    **Multi-worker guard**: when ``uvicorn --workers N`` runs, the
    lifespan runs N times in N processes. We only want ONE process
    to hold the LISTEN connection. The ``BacktestJobListener``
    itself races for a PG advisory lock inside ``_reconnect`` —
    first worker to grab it becomes the holder; the others get
    ``is_holder=False`` and stay quiet, so the SSE generators on
    those workers fall back to 1 s polling (still functional, just
    slightly higher latency). The lock is released explicitly in
    ``stop()``.
    """
    await pg_pool.init()

    listener = BacktestJobListener()
    await listener.start()  # may silently fail to be the holder

    if listener.is_holder:
        # Wire into the 3 SSE service modules so generators
        # ``subscribe(job_id)`` and wake up within ~10ms of a
        # worker-side ``pg_notify``.
        job_svc._LISTENER = listener
        sweep_svc._LISTENER = listener
        wf_svc._LISTENER = listener
    else:
        # Non-holder workers — leave _LISTENER unset (the SSE
        # generators check ``if _LISTENER is None`` and fall back
        # to polling). Also reset the service-module globals so
        # a previous holder that got rotated out doesn't leave a
        # stale listener behind.
        job_svc._LISTENER = None
        sweep_svc._LISTENER = None
        wf_svc._LISTENER = None
        # The listener object is not useful on this worker; we
        # still call ``stop()`` to clean up the failed-to-acquire
        # conn and the would-be subscribers dict.
        await listener.stop()
        listener = None  # noqa: F841 — for the ``finally`` clause

    try:
        yield
    finally:
        if listener is not None:
            await listener.stop()
        job_svc._LISTENER = None
        sweep_svc._LISTENER = None
        wf_svc._LISTENER = None
        await pg_pool.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="GetRich API",
        version="1.1.0",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )

    # Install the per-request log filter on the ROOT logger so it
    # applies to every existing ``logging.getLogger(__name__)``
    # caller in the codebase. The filter is idempotent (adding
    # the same instance twice is a no-op on subsequent calls
    # because we check by identity), so re-creating the app
    # under ``uvicorn --reload`` doesn't stack filters.
    _root_logger = logging.getLogger()
    if not any(isinstance(f, RequestIdLogFilter) for f in _root_logger.filters):
        _root_logger.addFilter(RequestIdLogFilter())

    # RequestIdMiddleware MUST be the OUTERMOST layer so that
    # every other middleware (security headers, metrics, CORS)
    # and every route handler share the same ``request_id``
    # context. We register it FIRST so Starlette's stack runs
    # it LAST on the way out, which means by the time the
    # response is built the var is still bound (we reset it in
    # the ``finally`` block). The body envelope's ``request_id``
    # and the ``X-Request-Id`` response header are both
    # populated from this single value.
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.web.cors_origins) or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Defense-in-depth security headers. Set on every response
    # (including 4xx/5xx envelopes and `/health`) so a future bug in
    # a router doesn't accidentally drop CSP. See middleware.py for
    # the rationale on each header.
    app.add_middleware(
        SecurityHeadersMiddleware,
        csp_policy=settings.web.csp_policy,
    )

    # Prometheus HTTP request metrics. The middleware is added AFTER
    # SecurityHeadersMiddleware so the response headers layer is
    # stable (CORS / security headers never see metric-induced
    # attribute changes). The middleware itself excludes /metrics
    # from its own counting so a Prometheus scrape loop doesn't
    # pollute the rate panel.
    app.add_middleware(MetricsMiddleware)

    register_exception_handlers(app)

    app.include_router(auth_router.router, prefix="/v1")
    app.include_router(backtest_jobs_router.router, prefix="/v1")
    app.include_router(backtest_runs_router.router, prefix="/v1")
    app.include_router(backtest_sweeps_router.router, prefix="/v1")
    app.include_router(backtest_walk_forwards_router.router, prefix="/v1")
    app.include_router(strategies_router.router, prefix="/v1")
    # 持仓诊断：/v1/diagnosis/*。契约见 getrich-design/portfolio-analysis/
    # 持仓诊断_表与接口设计.md §7.1（该文档写的 /api/v1 前缀与本仓不符，以此处为准）。
    app.include_router(diagnosis_router.router, prefix="/v1")
    # 选股展示：策略列表/详情/标的池走 pick.* 两张表，与择时策略的
    # /v1/strategies 分开 —— 选股策略 P0 没有业绩数字，混在一起会让
    # 前端拿到一堆 null 并误以为策略跑输了。
    app.include_router(picks_router.strategies_router, prefix="/v1")
    app.include_router(picks_router.picks_router, prefix="/v1")
    app.include_router(signals_router.router, prefix="/v1")
    app.include_router(subscriptions_router.router, prefix="/v1")
    app.include_router(signal_settings_router.router, prefix="/v1")
    app.include_router(user_router.router, prefix="/v1")
    app.include_router(payments_router.router, prefix="/v1")
    # Admin-only backoffice routes (strategy import / preview / commit / history).
    # All endpoints guarded by ``require_admin`` — see
    # ``routers/admin_imports.py`` for the per-endpoint contract.
    app.include_router(admin_imports_router.router, prefix="/v1")
    app.include_router(picks_router.admin_router, prefix="/v1")

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics", tags=["meta"])
    async def metrics() -> Response:
        """Prometheus exposition endpoint (text format).

        Mounted at the un-prefixed ``/metrics`` path (NOT under
        ``/v1``) so the default ``prometheus.yml`` scrape config
        ``/metrics`` works out of the box. The endpoint is
        intentionally NOT auth-protected — Prometheus scrapers
        don't carry user JWTs. The risk surface is bounded: the
        payload exposes the metric NAMES + the current counter
        values, not user data. The endpoint does NOT touch the
        DB / CH / Redis (it reads the in-process registry).
        """
        body, content_type = render_metrics()
        return Response(content=body, media_type=content_type)

    return app


app = create_app()
