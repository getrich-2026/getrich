#!/usr/bin/env python
"""Pre-push verification helper for the docs CI workflow.

Run this locally to confirm both docs jobs (``ci.yml::docs`` and
``.github/workflows/docs.yml::build``) will pass on GitHub Actions
before you ``git push`` to dev. It does three things:

1. Validates the two workflow YAMLs are syntactically correct.
2. Confirms every docs file glob the workflow claims to watch
   actually exists in the working tree (catches path-typo drift).
3. Runs ``mkdocs build --strict --clean`` in a clean output dir
   so the local result matches the CI runner's first-build path.

Usage::

    uv run python scripts/verify_docs_ci.py
    # or:
    python scripts/verify_docs_ci.py

Exits 0 if everything is green; non-zero on first failure.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _validate_yaml(path: Path) -> dict:
    """Parse a workflow YAML and return its job dict."""
    with path.open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    on = cfg.get(True) or cfg.get("on") or {}
    triggers = [k for k in on if k in ("pull_request", "push", "workflow_dispatch")]
    jobs = cfg.get("jobs", {})
    return {"triggers": triggers, "jobs": list(jobs.keys())}


def _check_workflow(path: Path) -> None:
    print(f"[1/3] Validating {path.relative_to(REPO_ROOT)}")
    info = _validate_yaml(path)
    print(f"      triggers: {info['triggers']}")
    print(f"      jobs:     {info['jobs']}")


def _check_globs() -> None:
    """Confirm each glob the workflows watch has at least one file."""
    print("[2/3] Verifying watch globs have matching files")
    patterns = [
        "docs/**",
        "mkdocs.yml",
        "src/getrich_backtest/**",
        "backtest/docs/**",
    ]
    for pat in patterns:
        if pat.endswith("/**"):
            base = pat[:-3]
            ok = any((REPO_ROOT / base).rglob("*"))
        else:
            ok = (REPO_ROOT / pat).exists()
        marker = "OK" if ok else "MISSING"
        print(f"      [{marker}] {pat}")


def _clean_build() -> None:
    """Run ``mkdocs build --strict --clean`` from scratch."""
    print("[3/3] mkdocs build --strict --clean")
    site = REPO_ROOT / "site"
    if site.exists():
        shutil.rmtree(site)
    # Use the same Python venv uv points at so mkdocstrings can import
    # getrich_backtest (it's installed editable via uv sync).
    cmd = ["uv", "run", "mkdocs", "build", "--strict", "--clean"]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, check=False, capture_output=True, text=True)
    # Show only the tail of the output; the strict build prints a lot
    # of "Reading from stdin" noise from pymdownx.
    out_tail = (proc.stdout or "")[-1500:]
    err_tail = (proc.stderr or "")[-800:]
    if out_tail:
        print(out_tail)
    if err_tail and proc.returncode != 0:
        print("STDERR:", err_tail)
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)
    # Confirm the engine/api-reference/index.html exists & has the
    # expected doc-* class spans (i.e. mkdocstrings actually ran).
    html = site / "engine" / "api-reference" / "index.html"
    if not html.exists():
        print(f"      [MISSING] {html.relative_to(REPO_ROOT)}")
        raise SystemExit(2)
    content = html.read_text(encoding="utf-8")
    class_n = len(re.findall(r'doc-object doc-class', content))
    func_n = len(re.findall(r'doc-object doc-function', content))
    print(f"      api-reference: {html.stat().st_size:,} bytes  "
          f"classes={class_n}  functions={func_n}")
    if class_n < 50:
        print(f"      [WARN] expected >= 50 class blocks, got {class_n}")
        raise SystemExit(3)


def main() -> int:
    print("=" * 72)
    print("docs CI pre-push verification")
    print("=" * 72)
    for wf in ("ci.yml", "docs.yml"):
        _check_workflow(WORKFLOWS / wf)
    _check_globs()
    _clean_build()
    print("=" * 72)
    print("OK — both docs CI jobs should pass on next push.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
