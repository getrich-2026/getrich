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


# ---------------------------------------------------------------- deploy-step checks (Round #1154)


def test_site_has_index_html_at_root() -> None:
    """GitHub Pages refuses to serve a site that lacks a top-level
    ``index.html``. The ``actions/upload-pages-artifact@v3`` step
    fails the deploy with no useful error if this is missing."""
    assert (SITE / "index.html").is_file(), (
        "site/index.html is missing - the gh-pages deploy will 404."
    )


def test_site_index_html_under_threshold() -> None:
    """A regression that pushes the api-reference onto the landing
    page would balloon index.html to 1+ MB. The mkdocs homepage
    with full nav is naturally 30-50 KB; flag anything > 100 KB."""
    size = (SITE / "index.html").stat().st_size
    assert size < 100_000, (
        f"site/index.html is {size:,} bytes (> 100 KB). "
        f"Did api-reference leak onto the landing page?"
    )


def test_site_total_under_threshold() -> None:
    """Total site size should be < 15 MB (round #1146 cut was
    8.4 MB; 50% headroom for content growth before re-trimming)."""
    total = sum(p.stat().st_size for p in SITE.rglob("*") if p.is_file())
    assert total < 15 * 1024 * 1024, (
        f"site/ total is {total / 1024 / 1024:.1f} MB (> 15 MB). "
        f"Re-trim needed; see Round #1146 for the optimization."
    )


def test_no_broken_subdirs() -> None:
    """Every site/ subdir (excluding mkdocs static assets) must
    have either its own index.html OR a deeper html/xml/json
    file. A dir with neither is a broken page that would 404
    on GitHub Pages."""
    skip = {"assets", "css", "js", "search", "search_index"}
    broken = []
    for d in SITE.iterdir():
        if not d.is_dir() or d.name in skip:
            continue
        if (d / "index.html").exists():
            continue
        files = list(d.rglob("*"))
        if not any(f.suffix in (".html", ".xml", ".json") for f in files if f.is_file()):
            broken.append(d.name)
    assert not broken, (
        f"site/ subdirs have no index.html and no static asset: {broken}"
    )
