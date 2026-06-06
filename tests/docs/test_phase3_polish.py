"""Tests for Phase 3 docs polish (Round #1149).

Catches two regressions in one file:
1. The order state machine in ``engine/execution-accounting.md``
   regresses back to ASCII box-drawing.
2. The mkdocs.yml site_url / keywords / social block gets dropped
   during a future refactor.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml


class _MkdocsYamlLoader(yaml.SafeLoader):
    """YAML loader that ignores mkdocs-specific ``!!python/name`` tags.

    mkdocs.yml declares things like
    ``emoji_generator: !!python/name:material.extensions.emoji.to_svg``
    which pyyaml rejects unless you supply a constructor. We don't
    need to resolve the tags; we just need to read the rest of the
    config (site_url, extra, etc.) as plain strings.
    """


def _ignore_python_name(loader: yaml.Loader, _suffix: str, _node: yaml.Node) -> Any:  # noqa: ANN401
    return None


_MkdocsYamlLoader.add_multi_constructor("tag:yaml.org,2002:python/name", _ignore_python_name)


REPO_ROOT = Path(__file__).resolve().parents[2]
EXEC_ACCT = REPO_ROOT / "docs" / "engine" / "execution-accounting.md"
MKDOCS = REPO_ROOT / "mkdocs.yml"


def test_execution_accounting_uses_mermaid_state_diagram() -> None:
    """The order state machine (§2.1) must render as Mermaid stateDiagram-v2.

    ASCII box-drawing was a maintenance trap: any character drift
    (trailing space, em-dash typo) makes the diagram un-renderable
    in pymdownx but the broken state is invisible until you scroll
    in the browser. Mermaid fails loud at build time.
    """
    text = EXEC_ACCT.read_text(encoding="utf-8")
    # Find the §2.1 section specifically
    section_start = text.find("### 2.1 订单状态机")
    assert section_start > 0, "§2.1 section missing"
    # Look at the next ~80 lines (state machine is the only diagram there)
    snippet = text[section_start : section_start + 2000]
    assert "```mermaid" in snippet, (
        "§2.1 order state machine regressed to non-Mermaid. "
        "Use a ```mermaid stateDiagram-v2 block instead of ASCII."
    )
    assert "stateDiagram-v2" in snippet, (
        "§2.1 mermaid block must be a stateDiagram-v2 (not flowchart)."
    )
    # All 5 statuses must appear in transitions
    for status in ("PENDING", "ACCEPTED", "FILLED", "REJECTED", "EXPIRED"):
        assert status in snippet, f"§2.1 missing transition through {status}"


def test_execution_accounting_no_ascii_box_drawing_in_section_2_1() -> None:
    """The §2.1 section must contain no box-drawing characters."""
    text = EXEC_ACCT.read_text(encoding="utf-8")
    section_start = text.find("### 2.1 订单状态机")
    snippet = text[section_start : section_start + 2000]
    # Find the closing ``` of the mermaid block
    fence_end = snippet.find("```\n", snippet.find("```mermaid") + 1)
    diagram = snippet[:fence_end]
    for ch in ("┌", "┐", "└", "┘", "│", "─", "╔", "╗", "╚", "╝", "║", "═"):
        assert ch not in diagram, f"§2.1 still contains ASCII box char {ch!r}"


def test_mkdocs_has_seo_meta() -> None:
    """mkdocs.yml must keep site_url + keywords + social for SEO."""
    cfg = yaml.load(MKDOCS.read_text(encoding="utf-8"), Loader=_MkdocsYamlLoader)
    assert cfg.get("site_url"), "site_url is required for canonical SEO"
    assert cfg["site_url"].startswith("http"), "site_url must be a full URL"
    extra = cfg.get("extra", {})
    assert "keywords" in extra, "extra.keywords missing"
    assert isinstance(extra["keywords"], list) and len(extra["keywords"]) >= 5, (
        "extra.keywords must be a list of >= 5 entries"
    )
    # At least one Chinese + one English keyword
    joined = " ".join(extra["keywords"])
    assert any(ord(c) > 127 for c in joined), (
        "extra.keywords should include Chinese terms for CN search"
    )
    assert any(c.isascii() for c in joined), (
        "extra.keywords should include English terms for EN search"
    )
    assert "social" in extra, "extra.social block missing"
    assert isinstance(extra["social"], list) and len(extra["social"]) >= 1, (
        "extra.social must list at least GitHub + site link"
    )


def test_mkdocs_social_links_are_real() -> None:
    """Every social entry must have a real https:// link."""
    cfg = yaml.load(MKDOCS.read_text(encoding="utf-8"), Loader=_MkdocsYamlLoader)
    social = cfg.get("extra", {}).get("social", [])
    for entry in social:
        assert entry.get("link", "").startswith("http"), (
            f"social entry {entry.get('name')!r} link is not a URL"
        )
        assert entry.get("name"), "social entry missing name"


def test_mkdocs_strict_build_unchanged() -> None:
    """The build still passes strict mode (the SEO additions can't break it)."""
    cfg = yaml.load(MKDOCS.read_text(encoding="utf-8"), Loader=_MkdocsYamlLoader)
    assert cfg.get("strict") is True, "mkdocs strict mode was turned off"


@pytest.mark.skipif(
    not (REPO_ROOT / "site" / "engine" / "execution-accounting" / "index.html").exists(),
    reason="site/ not built; run `mkdocs build --strict` first",
)
def test_execution_accounting_html_has_mermaid_state_diagram() -> None:
    """The built HTML must contain a Mermaid <pre class=mermaid> with stateDiagram-v2.

    Mermaid renders client-side via JS, so the build output is a
    ``<pre class="mermaid"><code>stateDiagram-v2 ...</code></pre>``
    block (not an inline <svg>). The Material theme loads
    ``mermaid.min.js`` and re-renders to SVG in the browser.
    """
    html = (REPO_ROOT / "site" / "engine" / "execution-accounting" / "index.html").read_text(
        encoding="utf-8"
    )
    assert "stateDiagram-v2" in html, "stateDiagram-v2 source not in built page"
    # Mermaid source block: the minifier drops the space, so the
    # rendered class attribute is `class=mermaid`.
    pre_blocks = re.findall(r'<pre class=mermaid><code>([^<]+)', html)
    assert pre_blocks, (
        "no <pre class=mermaid><code> block found; Mermaid source missing from build"
    )
    # Find the state diagram among the blocks (the page also has a flowchart in §1)
    state_blocks = [b for b in pre_blocks if "stateDiagram-v2" in b]
    assert state_blocks, (
        f"none of the {len(pre_blocks)} Mermaid blocks is a stateDiagram; "
        f"first block starts: {pre_blocks[0][:80]!r}"
    )
