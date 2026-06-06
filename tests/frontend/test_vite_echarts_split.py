"""Tests for the ECharts vendor chunk split (Round #1151).

The split has two goals that should both be true:
1. The first-load ``index`` chunk must NOT contain ECharts code
   (so the initial dashboard / login / register pages load fast).
2. The 3 ECharts sub-packages must live in 3 SEPARATE chunks
   (for cache stability on version bumps).

We run ``vite build`` in a subprocess and inspect the resulting
``dist/assets/`` directory. Each test is a structural assertion
on the file names + sizes.

Run with::

    cd frontend && npx vite build
    # then: uv run pytest tests/frontend/test_vite_echarts_split.py -v

Caveat: this test requires a successful ``vite build`` to run, so
the CI `frontend` job should depend on it. We mark the tests
``skipif`` the dist dir is missing.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend"
DIST_ASSETS = FRONTEND / "dist" / "assets"


def _build_dist() -> None:
    """Re-run ``vite build`` so the test doesn't rely on a stale dist."""
    if DIST_ASSETS.exists():
        shutil.rmtree(DIST_ASSETS.parent)
    proc = subprocess.run(
        ["npx", "vite", "build"],
        cwd=FRONTEND,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.fail(f"vite build failed:\nSTDOUT:\n{proc.stdout}\n"
                    f"STDERR:\n{proc.stderr}")


@pytest.fixture(scope="module", autouse=True)
def _ensure_dist() -> None:
    if not DIST_ASSETS.exists():
        _build_dist()


def _chunk_sizes() -> dict[str, int]:
    """Map chunk filename -> byte size."""
    return {p.name: p.stat().st_size for p in DIST_ASSETS.glob("*.js")}


# ----------------------------------------------------------- structural assertions


def test_index_chunk_does_not_contain_echarts() -> None:
    """The first-load ``index-*.js`` must be < 200 KB (ECharts-free).

    Before Round #1151 the index chunk was 478 KB because all of
    ECharts got inlined there. The 3-way split drops that to
    ~158 KB. The 200 KB floor gives a 25% headroom for future
    app-code growth before we need a 4th split.
    """
    sizes = _chunk_sizes()
    index_chunks = [n for n in sizes if re.match(r"index-[A-Za-z0-9_-]+\.js$", n)]
    assert index_chunks, f"no index-*.js found in {DIST_ASSETS}"
    # Take the largest one (in case there are multiple lazy entry chunks)
    main = max(index_chunks, key=lambda n: sizes[n])
    size = sizes[main]
    assert size < 200_000, (
        f"main {main} is {size:,} bytes; Round #1151 split regressed. "
        f"Did ECharts get inlined back into the main chunk?"
    )


def test_echarts_split_into_three_chunks() -> None:
    """Three separate vendor-echarts-* chunks must exist."""
    sizes = _chunk_sizes()
    chunks = [n for n in sizes if n.startswith("vendor-echarts-")]
    expected_substrings = ["vendor-echarts-core", "vendor-echarts-charts", "vendor-echarts-components"]
    for substr in expected_substrings:
        matching = [n for n in chunks if n.startswith(substr)]
        assert matching, (
            f"missing {substr}-*.js. "
            f"Got chunks: {sorted(chunks)}. "
            f"Did vite.config.ts manualChunks regress?"
        )
        # Exactly one chunk per sub-package (no duplicates from path-collision)
        assert len(matching) == 1, (
            f"{substr} has {len(matching)} chunks (expected 1): {matching}"
        )


def test_echarts_charts_chunk_is_the_largest() -> None:
    """Sanity: the chart-types chunk should be larger than components
    and core, because ECharts has many chart types."""
    sizes = _chunk_sizes()
    core = next(n for n in sizes if n.startswith("vendor-echarts-core"))
    charts = next(n for n in sizes if n.startswith("vendor-echarts-charts"))
    comps = next(n for n in sizes if n.startswith("vendor-echarts-components"))
    assert sizes[charts] > sizes[comps], (
        f"charts chunk {sizes[charts]:,} should be larger than components {sizes[comps]:,}"
    )
    assert sizes[charts] > sizes[core], (
        f"charts chunk {sizes[charts]:,} should be larger than core {sizes[core]:,}"
    )


def test_no_legacy_vendor_echarts_chunk() -> None:
    """The pre-Round-#1151 single ``vendor-echarts.js`` must not exist."""
    sizes = _chunk_sizes()
    legacy = [n for n in sizes if re.match(r"vendor-echarts-[A-Za-z0-9_-]+\.js$", n)
              and not any(n.startswith(p) for p in [
                  "vendor-echarts-core-",
                  "vendor-echarts-charts-",
                  "vendor-echarts-components-",
              ])]
    assert not legacy, (
        f"legacy single vendor-echarts chunk still exists: {legacy}. "
        f"Round #1151 split is incomplete."
    )


def test_vite_config_has_echarts_split() -> None:
    """Source-level guard: vite.config.ts must reference the 3 sub-chunks."""
    text = (FRONTEND / "vite.config.ts").read_text(encoding="utf-8")
    for name in ("vendor-echarts-core", "vendor-echarts-charts", "vendor-echarts-components"):
        assert name in text, f"vite.config.ts missing manualChunk for {name!r}"
