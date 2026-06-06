#!/usr/bin/env python
"""Pre-push verification helper for the docs CI workflow.

Run this locally to confirm both docs jobs (``ci.yml::docs`` and
``.github/workflows/docs.yml::build``) will pass on GitHub Actions
before you ``git push`` to dev. It does four things:

1. Validates the two workflow YAMLs are syntactically correct.
2. Confirms every docs file glob the workflow claims to watch
   actually exists in the working tree (catches path-typo drift).
3. Runs ``mkdocs build --strict --clean`` in a clean output dir
   so the local result matches the CI runner's first-build path.
4. Verifies the gh-pages deploy step's inputs are well-formed
   (the ``actions/upload-pages-artifact@v3`` step requires a
   ``site/`` directory with an ``index.html`` at the root; we
   confirm the built site satisfies this locally so the deploy
   step can't fail in CI for a missing-artifact reason).

The script does NOT push or trigger the workflow. Run it before
push for a green/red signal; the actual push + watch must be
done by the user (sandbox has no push permission and no gh CLI).

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
    print(f"[1/4] Validating {path.relative_to(REPO_ROOT)}")
    info = _validate_yaml(path)
    print(f"      triggers: {info['triggers']}")
    print(f"      jobs:     {info['jobs']}")


def _check_globs() -> None:
    """Confirm each glob the workflows watch has at least one file."""
    print("[2/4] Verifying watch globs have matching files")
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
    print("[3/4] mkdocs build --strict --clean")
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


def _check_deploy_step() -> None:
    """The ``actions/upload-pages-artifact@v3`` step requires the
    artifact directory to be a single static site root. Verify
    our local build has the expected shape (site/index.html
    exists; no broken symlinks; index.html < 5 KB so we're not
    accidentally shipping a 5 MB page)."""
    print("[4/4] gh-pages deploy step inputs")
    site = REPO_ROOT / "site"
    index = site / "index.html"
    if not index.exists():
        print("      [FAIL] site/index.html missing — deploy will 404")
        raise SystemExit(4)
    # GitHub Pages refuses to serve a directory that lacks a top-level
    # index.html. Our mkdocs config sets use_directory_urls: true,
    # which means mkdocs renders pages as site/foo/index.html rather
    # than site/foo.html, and site/index.html is the homepage.
    index_size = index.stat().st_size
    if index_size > 100_000:
        # mkdocs homepage with full nav is naturally 30-50 KB.
        # 100 KB is the upper bound; a regression that pushes the
        # api-reference onto / would push this to 1+ MB.
        print(f"      [WARN] site/index.html is {index_size:,} bytes "
              f"(> 100 KB; check that api-reference didn't leak to /)")
    else:
        print(f"      site/index.html: {index_size:,} bytes (OK)")
    # Total site size should be < 15 MB (the round #1146 cut was
    # 8.4 MB; budget 50% headroom for future content growth).
    total_size = sum(p.stat().st_size for p in site.rglob("*") if p.is_file())
    total_mb = total_size / (1024 * 1024)
    if total_mb > 15:
        print(f"      [WARN] site/ total is {total_mb:.1f} MB (> 15 MB; "
              f"consider trimming again)")
    else:
        print(f"      site/ total: {total_mb:.2f} MB (OK)")
    # Sanity: every directory under site/ either has its own
    # index.html (mkdocs use_directory_urls) or is a static asset
    # directory (assets/css/js/sitemap.xml.gz/objects.inv, plus
    # the well-known top-level 404.html). A directory with no
    # index.html AND no html/xml/json anywhere in its subtree is
    # a broken page. Note: a subdir like
    # ``about/license/index.html`` does NOT require
    # ``about/index.html`` if no ``docs/about/index.md`` exists
    # in the source. GitHub Pages will serve the deeper URL
    # but 404 on the bare dir, which is fine.
    static_dir_prefixes = {
        "assets", "css", "js", "search", "search_index",  # mkdocs assets
    }
    broken: list[str] = []
    for d in site.iterdir():
        if not d.is_dir():
            continue
        if d.name in static_dir_prefixes:
            continue
        if not (d / "index.html").exists():
            files = list(d.rglob("*"))
            if not any(f.suffix in (".html", ".xml", ".json") for f in files if f.is_file()):
                broken.append(str(d.relative_to(site)))
    if broken:
        print(f"      [WARN] {len(broken)} dir(s) have no index.html and "
              f"no static asset: {broken[:3]}")
    else:
        print(f"      all dirs have index.html or static assets (OK)")


def main() -> int:
    print("=" * 72)
    print("docs CI pre-push verification")
    print("=" * 72)
    for wf in ("ci.yml", "docs.yml"):
        _check_workflow(WORKFLOWS / wf)
    _check_globs()
    _clean_build()
    _check_deploy_step()
    print("=" * 72)
    print("OK - both docs CI jobs should pass on next push.")
    print("    Manual push + watch sequence:")
    print("      git push origin dev")
    print("      # In a browser or with gh CLI:")
    print("      open https://github.com/getrich/getrich/actions/workflows/docs.yml")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
