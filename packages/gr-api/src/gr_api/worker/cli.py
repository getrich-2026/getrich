"""Worker CLI: thin wrapper over ``celery`` that picks up our app.

Run via:

* ``python -m gr_api.worker.cli worker`` — start a Celery worker
  (consumes Redis queues, runs ``backtest.run_job`` /
  ``sweep.run_job`` / ``walk_forward.run_job``).
* ``python -m gr_api.worker.cli beat`` — placeholder for a
  future Celery beat scheduler (no scheduled jobs in this round; the
  live-signal path is scheduled independently).

We ``os.execvp`` straight into the ``celery`` entrypoint so process
metadata (PID, command line) is honest — operators see the canonical
``celery worker ...`` process tree in ``ps`` and ``systemd-cgtop``.
"""

from __future__ import annotations

import os
import sys

from gr_data.config.settings import load_settings


def main() -> None:
    """Dispatch to ``celery worker`` / ``celery beat``.

    Settings are loaded eagerly so the Celery app's broker URL is
    sourced from the same ``.env`` as the API process. Logging is
    configured in the new process by the Celery setup_logging signal.
    """
    cfg = load_settings()
    # exec 后 Python 进程被替换；日志配置交给 Celery setup_logging 信号。

    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)

    sub = sys.argv[1]
    if sub == "worker":
        argv = [
            "celery",
            "-A",
            "gr_api.worker.celery_app",
            "worker",
            f"--loglevel={cfg.logging.level}",
            *sys.argv[2:],
        ]
    elif sub == "beat":
        argv = [
            "celery",
            "-A",
            "gr_api.worker.celery_app",
            "beat",
            f"--loglevel={cfg.logging.level}",
            *sys.argv[2:],
        ]
    else:
        print(f"unknown subcommand: {sub!r} (expected 'worker' or 'beat')", file=sys.stderr)
        sys.exit(2)

    os.execvp("celery", argv)


if __name__ == "__main__":
    main()
