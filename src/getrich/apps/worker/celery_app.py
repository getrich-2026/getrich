"""Celery app factory for the backtest worker pool.

The Celery app is the broker-facing surface: clients call
``app.send_task("backtest.run_job", args=[job_id])`` to enqueue, and
``celery -A getrich.apps.worker.celery_app worker`` to consume.

Configuration is sourced from :class:`getrich.config.settings.WorkerConfig`:

* ``GETRICH_WORKER_BACKEND=celery`` must be set on both the API process
  (so the dispatcher takes the celery branch) and the worker process
  (so the worker is even importable — guard below).
* ``GETRICH_BROKER_URL`` is the Redis URL the broker uses for queue
  state. ``GETRICH_RESULT_BACKEND`` is the Redis URL the result backend
  uses (defaults to ``GETRICH_BROKER_URL``).
* ``GETRICH_FLOWER_URL`` is for the monitoring UI; not consumed by the
  app itself, just documented here for ops.

Key Celery settings chosen for this workload:

* ``task_acks_late=True`` — the worker only ACKs the broker after the
  op finishes. If the worker crashes mid-job, the broker re-delivers
  the task. The DB-side ``claim_next_queued`` (with
  ``FOR UPDATE SKIP LOCKED``) prevents duplicate execution.
* ``task_reject_on_worker_lost=True`` — paired with ``acks_late``, a
  worker that vanishes mid-task makes the message available to other
  workers instead of discarding it.
* ``worker_prefetch_multiplier=1`` — never prefetch more than one task
  at a time. Backtest jobs can take minutes; prefetching more would
  pin jobs to a busy worker.
* ``broker_connection_retry_on_startup=True`` — when the worker starts
  before Redis is up (common in systemd), it retries instead of
  crashing the unit.
"""

from __future__ import annotations

from celery import Celery

from getrich.config.settings import settings


def make_celery_app() -> Celery:
    """Build the Celery app wired to the configured Redis broker.

    Imports the task module eagerly so the three run_job tasks are
    registered with the app at import time — this lets callers use
    ``app.send_task("backtest.run_job", ...)`` without first having to
    import the worker process.
    """
    app = Celery(
        "getrich",
        broker=settings.worker.broker_url,
        backend=settings.worker.result_backend,
        include=["getrich.apps.worker.tasks"],
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

    return app


# A module-level singleton so callers can do
# ``from getrich.apps.worker.celery_app import app`` without
# re-constructing on every import.
app = make_celery_app()
