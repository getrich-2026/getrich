"""Worker CLI: thin wrapper over ``celery`` that picks up our app.

Run via:

* ``python -m getrich.apps.worker.cli worker`` — start a Celery worker
  (consumes Redis queues, runs ``backtest.run_job`` /
  ``sweep.run_job`` / ``walk_forward.run_job``).
* ``python -m getrich.apps.worker.cli beat`` — placeholder for a
  future Celery beat scheduler (no scheduled jobs in this round; the
  live-signal path is scheduled independently).

We ``os.execvp`` straight into the ``celery`` entrypoint so process
metadata (PID, command line) is honest — operators see the canonical
``celery worker ...`` process tree in ``ps`` and ``systemd-cgtop``.
"""

from __future__ import annotations

import os
import sys

from getrich.config.settings import load_settings


def main() -> None:
    """Dispatch to ``celery worker`` / ``celery beat``.

    Settings are loaded eagerly so the Celery app's broker URL is
    sourced from the same ``.env`` as the API process. Logging is
    configured so worker log lines match the API log format.
    """
    cfg = load_settings()
    if hasattr(cfg, "setup_logging"):
        cfg.setup_logging()

    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)

    sub = sys.argv[1]
    if sub == "worker":
        argv = [
            "celery",
            "-A",
            "getrich.apps.worker.celery_app",
            "worker",
            "--loglevel=INFO",
            *sys.argv[2:],
        ]
    elif sub == "beat":
        argv = [
            "celery",
            "-A",
            "getrich.apps.worker.celery_app",
            "beat",
            "--loglevel=INFO",
            *sys.argv[2:],
        ]
    else:
        print(f"unknown subcommand: {sub!r} (expected 'worker' or 'beat')", file=sys.stderr)
        sys.exit(2)

    os.execvp("celery", argv)


if __name__ == "__main__":
    main()
