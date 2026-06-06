"""Tests for ``scripts/verify_docs_ci.py``.

The script is a thin wrapper around three observable things:
1. Workflow YAML files are parseable
2. Watched globs have at least one matching file
3. ``mkdocs build --strict --clean`` produces an api-reference page
   with at least 50 class blocks rendered

Each test exercises one of these in isolation so a future regression
fails with a clear pointer.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
SITE = REPO_ROOT / "site"


def test_verify_script_exists() -> None:
    assert (SCRIPTS / "verify_docs_ci.py").is_file()


def test_verify_script_importable() -> None:
    """The script must import cleanly (no syntax errors, no missing deps)."""
    proc = subprocess.run(
        [sys.executable, "-c", "import importlib.util, sys; "
         f"spec = importlib.util.spec_from_file_location('v', r'{SCRIPTS / 'verify_docs_ci.py'}'); "
         "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print('ok')"],
        check=True, capture_output=True, text=True,
    )
    assert proc.stdout.strip() == "ok"


def test_ci_yml_has_docs_job() -> None:
    """``.github/workflows/ci.yml`` must keep its ``docs`` defense-in-depth job."""
    cfg = yaml.safe_load((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))
    jobs = cfg.get("jobs", {})
    assert "docs" in jobs, "ci.yml::docs job was removed; restore for path-glob drift defense"
    job = jobs["docs"]
    # The job must run `mkdocs build --strict` to keep its teeth
    steps_blob = "\n".join(
        str(s.get("run", "")) for s in job.get("steps", [])
    )
    assert "mkdocs build --strict" in steps_blob, (
        "ci.yml::docs no longer runs `mkdocs build --strict`; "
        "add the strict build to keep warnings-as-errors"
    )


def test_docs_yml_has_build_and_deploy() -> None:
    """``.github/workflows/docs.yml`` must keep both build + deploy jobs."""
    cfg = yaml.safe_load((WORKFLOWS / "docs.yml").read_text(encoding="utf-8"))
    jobs = cfg.get("jobs", {})
    assert "build" in jobs, "docs.yml::build job missing"
    assert "deploy" in jobs, "docs.yml::deploy job missing"
    # deploy must depend on build
    assert "build" in jobs["deploy"].get("needs", []), (
        "docs.yml::deploy must `needs: build` to deploy only on green builds"
    )
    # build must be strict
    blob = "\n".join(str(s.get("run", "")) for s in jobs["build"].get("steps", []))
    assert "mkdocs build --strict" in blob, "docs.yml::build must use --strict"


def test_watch_globs_match_real_paths() -> None:
    """Globs the workflows claim to watch must have at least one matching file."""
    # Mirrors the patterns declared in both workflows
    for pat in ["docs", "mkdocs.yml", "src/getrich_backtest", "backtest/docs"]:
        if pat.endswith(".yml") or pat.endswith(".md"):
            assert (REPO_ROOT / pat).exists(), f"watched path missing: {pat}"
        else:
            assert (REPO_ROOT / pat).is_dir(), f"watched dir missing: {pat}"


@pytest.mark.skipif(
    not (SITE / "engine" / "api-reference" / "index.html").exists(),
    reason="site/ not built; run `mkdocs build --strict` first",
)
def test_api_reference_html_has_class_blocks() -> None:
    """Sanity check: the built page must contain real mkdocstrings output.

    A regression where ``show_source: true`` leaks back to global, or
    where the directive targets silently stop resolving, would drop
    this number. We assert >= 50 class blocks (current: 71).
    """
    html = (SITE / "engine" / "api-reference" / "index.html").read_text(encoding="utf-8")
    n = len(re.findall(r'doc-object doc-class', html))
    assert n >= 50, (
        f"api-reference only renders {n} classes (expected >= 50). "
        f"Did a mkdocstrings directive silently stop resolving?"
    )
