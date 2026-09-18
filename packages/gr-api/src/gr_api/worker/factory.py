"""按调用方配置创建 Celery 应用；无模块级配置加载。"""

from __future__ import annotations

from celery import Celery
from gr_api.config import WorkerSettings


def make_celery_app(settings: WorkerSettings) -> Celery:
    """创建队列客户端并声明任务模块；任务由 Celery loader 加载。"""
    app = Celery(
        "getrich",
        broker=settings.worker.broker_url,
        backend=settings.worker.result_backend,
        include=["gr_api.worker.tasks"],
    )

    # Routing rules: keep the default queue today; future per-job-type
    # queues (e.g. ``sweep``, ``walk_forward``) can be routed here
    # without touching call sites.
    app.conf.task_routes = {
        "backtest.run_job": {"queue": "default"},
        "sweep.run_job": {"queue": "default"},
        "walk_forward.run_job": {"queue": "default"},
    }

    # Reliability: at-least-once delivery, no early prefetching.
    app.conf.task_acks_late = True
    app.conf.task_reject_on_worker_lost = True
    app.conf.worker_prefetch_multiplier = 1
    app.conf.broker_connection_retry_on_startup = True

    # Serialization: keep JSON for the payload (job_id is a str).
    app.conf.task_serializer = "json"
    app.conf.result_serializer = "json"
    app.conf.accept_content = ["json"]

    app.getrich_settings = settings
    return app
