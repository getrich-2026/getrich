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


# ---------------------------------------------------------------- live-signal-pipeline (Round #1155)
#
# Round #1155 introduces ``docs/platform/live-signal-pipeline.md``: the
# first end-to-end "1 tick" sequenceDiagram for the GetRich live
# signal path (systemd timer → Celery worker → LiveDataProvider →
# ClickHouse → LiveRiskMonitor → LiveSignalRunner → Strategy →
# EvalSignalWriter → PostgreSQL signals table → AlertChannel). The
# page is the platform-side companion to ``engine/live-signals.md``,
# which is the engine-side walkthrough. Both pages link to each
# other; this set of tests guards the platform page from regressing
# back to prose ("...then this calls that...") and locks the
# end-to-end actor set so a future refactor that drops one role
# (e.g. removes the LiveRiskMonitor alt branch) fails loud.


LIVE_PIPELINE_DOC = REPO_ROOT / "docs" / "platform" / "live-signal-pipeline.md"
LIVE_PIPELINE_HTML = REPO_ROOT / "site" / "platform" / "live-signal-pipeline" / "index.html"


def test_live_signal_pipeline_doc_exists() -> None:
    """The page must be present and non-empty (catches accidental deletion)."""
    assert LIVE_PIPELINE_DOC.is_file(), (
        "docs/platform/live-signal-pipeline.md is missing — "
        "the end-to-end live signal sequence diagram has no home"
    )
    text = LIVE_PIPELINE_DOC.read_text(encoding="utf-8")
    assert len(text) > 2000, (
        f"live-signal-pipeline.md is suspiciously short ({len(text)} chars); "
        f"expected a full tick walkthrough (>2KB)"
    )


def test_live_signal_pipeline_uses_mermaid_sequence_diagram() -> None:
    """§1 must be a ``sequenceDiagram`` (not a flowchart, not ASCII).

    ASCII prose like ``Timer -> Worker -> LDP -> ...`` was the
    pre-Round-#1155 state; it loses the swimlane clarity that
    sequenceDiagram gives. A future regression to ASCII hides
    the actor boundaries and breaks the §2 "8-step walkthrough"
    that depends on the diagram numbering.
    """
    text = LIVE_PIPELINE_DOC.read_text(encoding="utf-8")
    section_start = text.find("## 1. 全景")
    assert section_start > 0, "§1 全景 section missing"
    snippet = text[section_start : section_start + 4000]
    assert "```mermaid" in snippet, (
        "§1 全景 regressed to non-Mermaid. "
        "Use a ```mermaid sequenceDiagram block (not ASCII / flowchart)."
    )
    assert "sequenceDiagram" in snippet, (
        "§1 mermaid block must be a sequenceDiagram, not a stateDiagram or flowchart"
    )


def test_live_signal_pipeline_lists_all_actors() -> None:
    """The sequence diagram must include the full actor set.

    The 5 process / external actors are:
    1. Timer (systemd)
    2. Worker (Celery)
    3. LiveDataProvider
    4. ClickHouse
    5. LiveRiskMonitor
    6. LiveSignalRunner
    7. Strategy (user code)
    8. EvalSignalWriter
    9. PostgreSQL signals table
    10. AlertChannel (Log/Webhook/Email)

    Dropping any one of these breaks the end-to-end story: the
    page is the ONLY place in the docs that names all 10 actors
    on one page (engine/live-signals.md only covers 5 of them).
    """
    text = LIVE_PIPELINE_DOC.read_text(encoding="utf-8")
    section_start = text.find("## 1. 全景")
    snippet = text[section_start : section_start + 4000]
    expected_actors = [
        "Timer",          # systemd
        "Worker",         # Celery
        "LiveDataProvider",
        "ClickHouse",
        "LiveRiskMonitor",
        "LiveSignalRunner",
        "Strategy",       # user code
        "EvalSignalWriter",
        "PostgreSQL",
        "AlertChannel",   # Log/Webhook/Email
    ]
    missing = [a for a in expected_actors if a not in snippet]
    assert not missing, (
        f"§1 sequence diagram missing actors: {missing}. "
        f"All 10 roles are required to tell the end-to-end story."
    )


def test_live_signal_pipeline_documents_alt_branch() -> None:
    """The diagram must show the alerts/non-empty branch.

    LiveRiskMonitor emits a RiskAlert; the alt branch proves the
    alerts go to AlertChannel (Log/Webhook/Email) AND the signal
    still lands in PostgreSQL with reason='ALERTED: ...'. Dropping
    this branch hides the "告警是旁路" design point and makes
    the page inconsistent with ``engine/live-signals.md``.
    """
    text = LIVE_PIPELINE_DOC.read_text(encoding="utf-8")
    section_start = text.find("## 1. 全景")
    snippet = text[section_start : section_start + 4000]
    # Mermaid sequenceDiagram alt branch syntax: ``alt alerts == []``
    assert "alt" in snippet, (
        "§1 sequence diagram missing the alt branch for alerts. "
        "Add: alt alerts == [] ... else alerts is non-empty ... end"
    )
    # And the explanatory Note about the旁路 (旁路 = bypass)
    assert "旁路" in text or "ALERTED" in text, (
        "Page must explain that alerts are a旁路 (bypass) channel "
        "and signals still land in PG with reason='ALERTED: ...'"
    )


def test_live_signal_pipeline_links_to_engine_live_signals() -> None:
    """The page must cross-link ``engine/live-signals.md``.

    The two pages are the platform-side / engine-side companion
    walkthroughs; breaking the link is the #1 way for new
    contributors to duplicate content instead of linking.
    """
    text = LIVE_PIPELINE_DOC.read_text(encoding="utf-8")
    assert "../engine/live-signals.md" in text, (
        "live-signal-pipeline.md must cross-link to ../engine/live-signals.md "
        "(the engine-side walkthrough). Add a link in §3-§6."
    )


def test_live_signal_pipeline_listed_in_mkdocs_nav() -> None:
    """mkdocs.yml must register the page under 平台指南.

    Without a nav entry the page is buildable but unreachable
    from the left sidebar (mkdocs warns under --strict, but
    the build still succeeds if the file exists in the source
    tree). This guard prevents that.
    """
    cfg = yaml.load(MKDOCS.read_text(encoding="utf-8"), Loader=_MkdocsYamlLoader)
    nav = cfg.get("nav", [])
    # nav is a list of (title | dict) entries; flatten to find the page path
    found = False
    for entry in nav:
        if not isinstance(entry, dict):
            continue
        for section in entry.values():
            if not isinstance(section, list):
                continue
            for item in section:
                if not isinstance(item, dict):
                    continue
                for value in item.values():
                    if value == "platform/live-signal-pipeline.md":
                        found = True
                        break
    assert found, (
        "platform/live-signal-pipeline.md is not in mkdocs.yml nav. "
        "Add it under 平台指南 (next to platform/architecture.md)."
    )


@pytest.mark.skipif(
    not LIVE_PIPELINE_HTML.exists(),
    reason="site/ not built; run `mkdocs build --strict` first",
)
def test_live_signal_pipeline_html_renders_sequence_diagram() -> None:
    """The built HTML must contain a Mermaid sequenceDiagram source block.

    Catches three regressions in one check:
    1. The mkdoc build silently dropping the page
    2. A directive typo that makes the sequenceDiagram not parse
    3. The minifier stripping the ``<pre class=mermaid>`` wrapper
    """
    html = LIVE_PIPELINE_HTML.read_text(encoding="utf-8")
    assert "sequenceDiagram" in html, (
        "sequenceDiagram source not in built page — "
        "did the §1 mermaid block fail to render?"
    )
    pre_blocks = re.findall(r'<pre class=mermaid><code>([^<]+)', html)
    assert pre_blocks, (
        "no <pre class=mermaid><code> block in built page; "
        "Mermaid source missing from build output"
    )
    seq_blocks = [b for b in pre_blocks if "sequenceDiagram" in b]
    assert seq_blocks, (
        f"none of the {len(pre_blocks)} Mermaid blocks is a sequenceDiagram; "
        f"the live signal flow is not visualized. "
        f"First block starts: {pre_blocks[0][:80]!r}"
    )


# ---------------------------------------------------------------- i18n / gh-pages deploy (Round #1156)
#
# Round #1156 has three moving parts:
# 1. ``docs/translations.md`` — i18n placeholder + status table
# 2. ``mkdocs.yml`` adds a ``Translations / 翻译: translations.md`` nav
#    entry so the page is reachable from the left sidebar
# 3. ``.github/workflows/docs.yml`` bumps
#    ``actions/upload-pages-artifact`` v3 -> v5 and
#    ``actions/deploy-pages`` v4 -> v5
#
# The first two are guards against accidental deletion of the i18n
# page (which is the placeholder for the future English mirror).
# The third is a guard against the actions falling back below
# GitHub's "Latest" major — older majors quietly lose security
# patches and the `node:24` runtime deploy-pages v5 ships with.


TRANSLATIONS_DOC = REPO_ROOT / "docs" / "translations.md"
RUNBOOK_DOC = REPO_ROOT / "docs" / "operations" / "runbook.md"
DOCS_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "docs.yml"


def test_translations_doc_exists() -> None:
    """The i18n placeholder must not be silently deleted.

    A future contributor who wants to nuke the ``Translations`` nav
    entry has to also delete this file (or rewrite it to be a stub
    redirect). The test makes the deletion a deliberate act.
    """
    assert TRANSLATIONS_DOC.is_file(), (
        "docs/translations.md is missing — Round #1156 i18n placeholder "
        "was deleted; restore it (or replace with a real i18n landing page)"
    )


def test_translations_documents_current_status_table() -> None:
    """The page must show a language status table so the placeholder
    doesn't read as 'we forgot English'."""
    text = TRANSLATIONS_DOC.read_text(encoding="utf-8")
    # 4 columns: 语言 / 状态 / 入口 / 维护者
    for col in ("语言", "状态", "入口", "维护者"):
        assert col in text, (
            f"translations.md status table is missing column {col!r}. "
            f"Use a 4-column table: | 语言 | 状态 | 入口 | 维护者 |"
        )
    # 4 expected languages: 中文 (current), 英文 (placeholder),
    # 日文 + 繁体 (未规划). Dropping one is a regression in the
    # i18n roadmap visibility.
    for lang in ("中文", "英文", "日文", "繁体"):
        assert lang in text, f"translations.md status table missing language {lang!r}"


def test_translations_explains_tech_choice() -> None:
    """The page must document WHY only Chinese for now + the future
    i18n candidate (mkdocs-static-i18n).

    Without the rationale, a contributor might "fix" the missing
    English by adding a second mkdocs.yml and splitting the
    workflows — which doubles the maintenance cost.
    """
    text = TRANSLATIONS_DOC.read_text(encoding="utf-8")
    assert "mkdocs-static-i18n" in text, (
        "translations.md must name mkdocs-static-i18n as the chosen "
        "i18n tool, otherwise a future contributor picks a heavier "
        "alternative (Crowdin / Transifex / split mkdocs.yml)"
    )
    assert "中文" in text, "page must mention current Chinese-only state"


def test_translations_listed_in_mkdocs_nav() -> None:
    """mkdocs.yml must keep the ``Translations / 翻译`` nav entry.

    Without the nav entry the page is buildable but unreachable
    from the left sidebar; mkdocs --strict would warn but not
    fail (mkdocs.yml has ``omitted_files: ignore`` in validation).
    """
    cfg = yaml.load(MKDOCS.read_text(encoding="utf-8"), Loader=_MkdocsYamlLoader)
    nav = cfg.get("nav", [])
    found_path = False
    found_title = False
    for entry in nav:
        if not isinstance(entry, dict):
            continue
        for title, value in entry.items():
            if value == "translations.md":
                found_path = True
            if "Translations" in str(title) or "翻译" in str(title):
                found_title = True
    assert found_path, (
        "translations.md is not in mkdocs.yml nav. "
        "Add `- Translations / 翻译: translations.md` at the top level."
    )
    assert found_title, (
        "Translations nav entry is missing the bilingual title "
        "(must contain 'Translations' or '翻译')"
    )


def test_runbook_has_documentation_ci_section() -> None:
    """The runbook must have a §12 "文档 CI 故障（gh-pages 部署）" section.

    Round #1156 added this; the test prevents future refactors
    from collapsing the section back into §1-§8 (which are
    runtime issues, not docs-CI issues).
    """
    text = RUNBOOK_DOC.read_text(encoding="utf-8")
    assert "## 12. 文档 CI 故障" in text, (
        "runbook.md is missing §12 文档 CI 故障. "
        "Add the section covering mkdocs build / gh-pages deploy / 404 / "
        "strict warnings / pre-push verification."
    )


def test_runbook_documentation_ci_lists_5_failure_modes() -> None:
    """§12 must cover at least 5 distinct failure modes.

    The section is only useful if a fresh SRE can find their symptom
    in < 30 seconds. 5 modes (build / deploy / 404 / strict warning
    / pre-push verification) is the minimum; dropping one means
    a real failure mode has no runbook entry.
    """
    text = RUNBOOK_DOC.read_text(encoding="utf-8")
    section_start = text.find("## 12. 文档 CI 故障")
    assert section_start > 0, "§12 not found"
    section = text[section_start:]
    # 5 sub-sections, each ### 12.N ... pattern
    expected_subtitles = (
        "### 12.1 症状：mkdocs build --strict 失败",
        "### 12.2 症状：gh-pages deploy 失败",
        "### 12.3 症状：部署后页面 404",
        "### 12.4 症状：strict-mode warning",
        "### 12.5 预防：pre-push 验证",
    )
    missing = [s for s in expected_subtitles if s not in section]
    assert not missing, (
        f"runbook §12 missing failure-mode sub-sections: {missing}. "
        f"Add all 5: build / deploy / 404 / strict warning / pre-push."
    )


def test_runbook_documentation_ci_references_verify_script() -> None:
    """§12.5 must point to ``scripts/verify_docs_ci.py`` (Round #1154 helper).

    The pre-push verification is the cheapest defense against docs
    CI red runs; the runbook must surface it.
    """
    text = RUNBOOK_DOC.read_text(encoding="utf-8")
    assert "verify_docs_ci.py" in text, (
        "runbook §12.5 must reference scripts/verify_docs_ci.py "
        "so SREs know to run it before pushing docs changes"
    )


def test_docs_workflow_uses_upload_pages_artifact_v5() -> None:
    """The gh-pages deploy step must use ``actions/upload-pages-artifact@v5``.

    Round #1156 upgraded from v3 to v5 (v4 changed the default to
    exclude hidden files; v5 tracks upload-artifact@v7). Going back
    to v3 is a regression — GitHub dropped v3 from the marketplace
    latest in Sep 2024 and security patches have stopped.
    """
    text = DOCS_WORKFLOW.read_text(encoding="utf-8")
    assert "actions/upload-pages-artifact@v5" in text, (
        "docs.yml deploy step dropped to an older actions/upload-pages-artifact "
        "version. Pin to @v5 (Round #1156 baseline)."
    )
    assert "actions/upload-pages-artifact@v3" not in text, (
        "docs.yml still uses actions/upload-pages-artifact@v3 — "
        "this version is unmaintained; bump to @v5"
    )


def test_docs_workflow_uses_deploy_pages_v5() -> None:
    """The gh-pages deploy step must use ``actions/deploy-pages@v5``.

    v5 (Mar 2026) updates Node to 24.x and ships the immutable
    action package workflow. v4 (Node 20) is end-of-life.
    """
    text = DOCS_WORKFLOW.read_text(encoding="utf-8")
    assert "actions/deploy-pages@v5" in text, (
        "docs.yml deploy step is on an older actions/deploy-pages "
        "version. Pin to @v5 (Round #1156 baseline)."
    )
    assert "actions/deploy-pages@v4" not in text, (
        "docs.yml still uses actions/deploy-pages@v4 — "
        "bump to @v5 for Node 24 + security patches"
    )


def test_docs_workflow_keeps_pages_environment() -> None:
    """The deploy job must keep the ``github-pages`` environment.

    GitHub Pages uses an OIDC `id-token` grant scoped to the
    `github-pages` environment; without the env block the deploy
    fails with a 403 from the OIDC handshake.
    """
    text = DOCS_WORKFLOW.read_text(encoding="utf-8")
    assert "environment:" in text, "docs.yml lost the `environment:` block"
    assert "github-pages" in text, (
        "docs.yml deploy job lost the `github-pages` environment "
        "(required for the OIDC id-token grant; deploy will 403 without it)"
    )
    # Both OIDC perms must be present
    assert "pages: write" in text, "docs.yml deploy lost `pages: write` permission"
    assert "id-token: write" in text, (
        "docs.yml deploy lost `id-token: write` permission "
        "(required for the OIDC handshake with github-pages env)"
    )

