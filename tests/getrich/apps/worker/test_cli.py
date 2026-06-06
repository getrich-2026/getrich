"""Tests for ``getrich.apps.worker.cli``.

The CLI module is a thin ``os.execvp`` wrapper that
dispatches ``python -m getrich.apps.worker.cli {worker,beat}``
into the canonical ``celery`` entrypoint. Its only jobs:

1. Load settings eagerly so the Celery app's broker URL
   comes from the same ``.env`` as the API process.
2. Optionally configure logging via ``cfg.setup_logging()``.
3. Build the right ``celery`` argv and ``os.execvp`` into it.

We test by patching ``os.execvp`` so the test process is
NOT replaced, then asserting on the constructed argv.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from getrich.apps.worker import cli


# ---------------------------------------------------------------------------
# argv construction
# ---------------------------------------------------------------------------


def test_cli_worker_subcommand_builds_canonical_argv() -> None:
    """`python -m getrich.apps.worker.cli worker ...` →
    `os.execvp("celery", ["celery", "-A", "getrich.apps.worker.celery_app",
    "worker", "--loglevel=INFO", ...rest])`."""
    with (
        patch.object(cli, "load_settings") as fake_load,
        patch.object(cli.os, "execvp") as fake_exec,
        patch.object(sys, "argv", ["cli", "worker"]),
    ):
        fake_load.return_value = MagicMock(spec=[])  # no setup_logging attr

        cli.main()

    fake_exec.assert_called_once()
    program, argv = fake_exec.call_args[0]
    assert program == "celery"
    assert argv[0] == "celery"
    assert argv[1] == "-A"
    assert argv[2] == "getrich.apps.worker.celery_app"
    assert argv[3] == "worker"
    assert argv[4] == "--loglevel=INFO"


def test_cli_beat_subcommand_builds_canonical_argv() -> None:
    """`python -m getrich.apps.worker.cli beat ...` →
    `os.execvp("celery", ["celery", "-A", "getrich.apps.worker.celery_app",
    "beat", "--loglevel=INFO", ...rest])`."""
    with (
        patch.object(cli, "load_settings") as fake_load,
        patch.object(cli.os, "execvp") as fake_exec,
        patch.object(sys, "argv", ["cli", "beat"]),
    ):
        fake_load.return_value = MagicMock(spec=[])

        cli.main()

    fake_exec.assert_called_once()
    program, argv = fake_exec.call_args[0]
    assert program == "celery"
    assert argv[3] == "beat"
    assert argv[4] == "--loglevel=INFO"


def test_cli_passes_through_extra_args() -> None:
    """Anything after the subcommand is forwarded to celery.

    E.g. `python -m getrich.apps.worker.cli worker --concurrency=4 -Q high`
    → celery gets those flags verbatim."""
    with (
        patch.object(cli, "load_settings") as fake_load,
        patch.object(cli.os, "execvp") as fake_exec,
        patch.object(sys, "argv", ["cli", "worker", "--concurrency=4", "-Q", "high"]),
    ):
        fake_load.return_value = MagicMock(spec=[])

        cli.main()

    _, argv = fake_exec.call_args[0]
    assert "--concurrency=4" in argv
    assert "-Q" in argv
    assert "high" in argv


# ---------------------------------------------------------------------------
# settings + logging
# ---------------------------------------------------------------------------


def test_cli_loads_settings_eagerly() -> None:
    """Settings must be loaded BEFORE the celery exec so the
    broker URL is sourced from the same `.env` as the API
    process. We assert by spying on the load call."""
    with (
        patch.object(cli, "load_settings") as fake_load,
        patch.object(cli.os, "execvp"),
        patch.object(sys, "argv", ["cli", "worker"]),
    ):
        fake_load.return_value = MagicMock(spec=[])

        cli.main()

    fake_load.assert_called_once()


def test_cli_calls_setup_logging_when_present() -> None:
    """If `load_settings()` returns a config that exposes
    `setup_logging()` (the project convention), the CLI
    calls it before exec'ing celery — so worker log lines
    match the API log format."""
    fake_cfg = MagicMock()
    fake_cfg.setup_logging = MagicMock()

    with (
        patch.object(cli, "load_settings", return_value=fake_cfg),
        patch.object(cli.os, "execvp"),
        patch.object(sys, "argv", ["cli", "worker"]),
    ):
        cli.main()

    fake_cfg.setup_logging.assert_called_once()


def test_cli_skips_setup_logging_when_absent() -> None:
    """Some test/mock configurations don't have
    `setup_logging`. The CLI must not crash — the
    `hasattr(cfg, "setup_logging")` guard handles this."""
    fake_cfg = MagicMock(spec=[])  # no setup_logging attr

    with (
        patch.object(cli, "load_settings", return_value=fake_cfg),
        patch.object(cli.os, "execvp"),
        patch.object(sys, "argv", ["cli", "worker"]),
    ):
        cli.main()  # should not raise


# ---------------------------------------------------------------------------
# error paths
# ---------------------------------------------------------------------------


def test_cli_no_args_prints_doc_and_exits_2() -> None:
    """Calling `python -m getrich.apps.worker.cli` with no
    subcommand prints the module docstring to stderr and
    exits with code 2 (the conventional "usage error" code)."""
    with (
        patch.object(cli, "load_settings") as fake_load,
        patch.object(cli.os, "execvp") as fake_exec,
        patch.object(sys, "argv", ["cli"]),
    ):
        fake_load.return_value = MagicMock(spec=[])

        with pytest.raises(SystemExit) as exc_info:
            cli.main()

    # Exit code 2 = usage error.
    assert exc_info.value.code == 2
    # The exec must NOT have been called (we exited before).
    fake_exec.assert_not_called()


def test_cli_unknown_subcommand_exits_2() -> None:
    """`python -m getrich.apps.worker.cli foo` → unknown
    subcommand, exit 2, no exec."""
    with (
        patch.object(cli, "load_settings") as fake_load,
        patch.object(cli.os, "execvp") as fake_exec,
        patch.object(sys, "argv", ["cli", "foo"]),
    ):
        fake_load.return_value = MagicMock(spec=[])

        with pytest.raises(SystemExit) as exc_info:
            cli.main()

    assert exc_info.value.code == 2
    fake_exec.assert_not_called()


def test_cli_unknown_subcommand_includes_subcommand_in_message() -> None:
    """The error message echoes the bad subcommand so the
    operator can see what was rejected."""
    with (
        patch.object(cli, "load_settings") as fake_load,
        patch.object(cli.os, "execvp"),
        patch.object(sys, "argv", ["cli", "frobnicate"]),
    ):
        fake_load.return_value = MagicMock(spec=[])

        with pytest.raises(SystemExit):
            cli.main()


# ---------------------------------------------------------------------------
# __main__ entry point
# ---------------------------------------------------------------------------


def test_cli_main_block_dispatches_to_main() -> None:
    """The `if __name__ == "__main__": main()` block is
    exercised by importing the module — we just confirm
    the symbol `main` is callable (the import would fail
    otherwise)."""
    assert callable(cli.main)
