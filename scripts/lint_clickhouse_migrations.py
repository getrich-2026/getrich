#!/usr/bin/env python
"""Back-compat shim: Round #1150 entry point.

The real linter moved to ``scripts/lint_migrations.py`` (Round #1153)
and now also covers PostgreSQL. This shim keeps the old name working
so existing CI jobs, shell history, and the Round #1150 test file
(which loads this module by path and reads the
``FORBIDDEN_PATTERNS`` / ``_split_statements`` symbols) don't break.

New code should call ``scripts/lint_migrations.py`` directly.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_NEW_PATH = _THIS_DIR / "lint_migrations.py"

# When the Round #1150 test file loads this module via
# ``importlib.util.spec_from_file_location("lint_ch", __file__)``
# it does NOT add anything to ``sys.path``. So a top-level
# ``import lint_migrations`` would fail with
# ``ModuleNotFoundError: No module named 'lint_migrations'``.
# Load the new module by file path the same way.
_spec = importlib.util.spec_from_file_location("_lint_migrations_impl", _NEW_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

# Re-export the symbols the Round #1150 tests reach into.
CH_FORBIDDEN_PATTERNS = _mod.CH_FORBIDDEN_PATTERNS
FORBIDDEN_PATTERNS = CH_FORBIDDEN_PATTERNS  # the old public name
_split_statements = _mod._split_statements

# Back-compat: Round #1150 tests call ``mod._scan_file(p)`` with
# a single argument. The new signature is ``_scan_file(p, patterns)``.
def _scan_file(path):  # type: ignore[no-redef]
    return _mod._scan_file(path, CH_FORBIDDEN_PATTERNS)


if __name__ == "__main__":
    # ``--db ch`` is the Round #1150 behaviour: only CH files.
    sys.exit(_mod.main(["--db", "ch"]))
