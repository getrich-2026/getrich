"""Smoke tests for ``.github/dependabot.yml``.

Dependabot's config schema is documented at
https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/configuration-options-for-the-dependabot.yml-file
and is validated by GitHub at PR-open time. A typo here
silences the bot for the whole repo — no error, just
"Dependabot is paused" forever.

We catch the typo's locally by:

1. Confirming the file exists and parses as YAML.
2. Asserting each ``updates[]`` entry has the required keys.
3. Asserting the three ecosystems we care about (pip, npm,
   github-actions) are all present.
4. Asserting the schedule is sane (not "every minute" or
   "every year" — both are valid schema but both are wrong
   for us).
5. Asserting the directory each ecosystem points to
   actually contains the corresponding lockfile /
   manifest.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = REPO_ROOT / ".github" / "dependabot.yml"


# --------------------------------------------------------------------
# 1. File presence + schema version
# --------------------------------------------------------------------


def test_dependabot_config_exists() -> None:
    """Dependabot looks for this path; placing it elsewhere
    requires a per-developer override."""
    assert CONFIG.is_file(), (
        f"missing config at {CONFIG.relative_to(REPO_ROOT)}"
    )


def test_dependabot_config_is_yaml_and_version_2() -> None:
    """GitHub only accepts ``version: 2``; v1 was the
    pre-2020 manifest format and is no longer supported.
    """
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert isinstance(cfg, dict)
    assert cfg.get("version") == 2, (
        f"dependabot.yml must use version: 2 (got {cfg.get('version')!r})"
    )


# --------------------------------------------------------------------
# 2. Required ecosystems
# --------------------------------------------------------------------


EXPECTED_ECOSYSTEMS = {
    "pip",
    "npm",
    "github-actions",
}


def test_required_ecosystems_are_present() -> None:
    """The three ecosystems we use must be configured; a
    missing one means Dependabot won't open PRs for it.
    """
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    actual = {
        entry["package-ecosystem"]
        for entry in cfg.get("updates", [])
    }
    missing = EXPECTED_ECOSYSTEMS - actual
    assert not missing, (
        f"dependabot.yml is missing ecosystems: {sorted(missing)}; "
        f"found: {sorted(actual)}"
    )


# --------------------------------------------------------------------
# 3. Per-entry structural checks
# --------------------------------------------------------------------


@pytest.fixture(scope="module")
def entries() -> list[dict]:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    return cfg.get("updates", [])


def test_every_entry_has_directory(entries: list[dict]) -> None:
    """``directory:`` is REQUIRED by the schema; without it
    Dependabot silently skips the entry.
    """
    for e in entries:
        assert "directory" in e, (
            f"ecosystem {e.get('package-ecosystem')!r} missing `directory`"
        )
        assert e["directory"], (
            f"ecosystem {e.get('package-ecosystem')!r} has empty `directory`"
        )


def test_every_entry_has_schedule(entries: list[dict]) -> None:
    """A schedule section is technically optional (defaults
    to weekly), but we want to be explicit so reviewers can
    see the cadence without reading Dependabot's defaults.
    """
    for e in entries:
        assert "schedule" in e, (
            f"ecosystem {e.get('package-ecosystem')!r} missing explicit "
            f"`schedule`; falling back to Dependabot default is opaque"
        )


def test_schedule_interval_is_weekly(entries: list[dict]) -> None:
    """We chose weekly on Monday to bundle patch updates
    into a single reviewable PR. Anything more frequent
    (daily) floods the queue; anything less (monthly)
    leaves CVEs unaddressed for weeks.
    """
    for e in entries:
        schedule = e.get("schedule", {})
        assert schedule.get("interval") == "weekly", (
            f"ecosystem {e.get('package-ecosystem')!r} schedule.interval "
            f"should be 'weekly' (got {schedule.get('interval')!r}); "
            f"see comment in .github/dependabot.yml for the why"
        )


def test_pr_limit_is_set(entries: list[dict]) -> None:
    """Default PR limit is 5; we override to 10 (or 3 for
    actions) to absorb bursty weeks. A missing limit means
    we accept Dependabot's 5-default, which usually results
    in 5 deferred PRs when npm has a big release.
    """
    for e in entries:
        assert "open-pull-requests-limit" in e, (
            f"ecosystem {e.get('package-ecosystem')!r} should set "
            f"open-pull-requests-limit explicitly"
        )


# --------------------------------------------------------------------
# 4. Directory + manifest cross-check
# --------------------------------------------------------------------


@pytest.mark.parametrize(
    "ecosystem,manifest_in_dir",
    [
        # pip: directory is "/" (repo root), manifest is
        # "pyproject.toml" alongside it.
        ("pip", "pyproject.toml"),
        # npm: directory is "/frontend", manifest is
        # "package.json" *inside* that directory.
        ("npm", "package.json"),
        # github-actions: directory is "/", and we just want
        # ANY workflow file to exist.
        ("github-actions", None),
    ],
)
def test_ecosystem_directory_contains_manifest(
    entries: list[dict], ecosystem: str, manifest_in_dir: str | None
) -> None:
    """Each ecosystem must point at a directory that actually
    contains its manifest. Otherwise Dependabot opens no PRs
    (with a silent warning in the Activity tab).
    """
    entry = next(
        (e for e in entries if e["package-ecosystem"] == ecosystem),
        None,
    )
    if entry is None:
        pytest.skip(f"ecosystem {ecosystem!r} not configured (covered above)")
    # Dependabot uses paths like "/" or "/frontend"; strip the
    # leading slash so pathlib treats them as relative to the
    # repo root (otherwise "/" is an absolute path on POSIX
    # and an invalid drive on Windows).
    rel_dir = entry["directory"].lstrip("/")
    base = (REPO_ROOT / rel_dir).resolve()
    if ecosystem == "github-actions":
        # Special: just confirm workflows exist somewhere under .github.
        assert base.is_dir(), (
            f"github-actions directory {entry['directory']!r} "
            f"does not exist (resolved: {base})"
        )
        assert any(base.glob("**/*.yml")) or any(base.glob("**/*.yaml")), (
            f"github-actions directory {entry['directory']!r} contains "
            f"no .yml workflows; Dependabot would have nothing to update"
        )
    else:
        assert base.is_dir(), (
            f"{ecosystem!r} directory {entry['directory']!r} does not "
            f"exist (resolved: {base})"
        )
        manifest = base / manifest_in_dir
        assert manifest.is_file(), (
            f"{ecosystem!r} directory {entry['directory']!r} should "
            f"contain {manifest_in_dir}, but it does not "
            f"(resolved: {manifest})"
        )


# --------------------------------------------------------------------
# 5. groups section (if present) must have valid update-types
# --------------------------------------------------------------------


VALID_UPDATE_TYPES = {
    "major", "minor", "patch",
    # The Dependabot schema also allows: "digest" (for
    # Docker base-image updates), but we don't use that.
}


def test_groups_have_valid_update_types(entries: list[dict]) -> None:
    """If you group updates, the update-types filter must be
    one Dependabot knows about. A typo (``"majer"``) means
    the group matches nothing and the PR is never opened.
    """
    for e in entries:
        groups = e.get("groups", {})
        if not groups:
            continue
        for name, group_cfg in groups.items():
            for ut in group_cfg.get("update-types", []):
                assert ut in VALID_UPDATE_TYPES, (
                    f"ecosystem {e.get('package-ecosystem')!r} group "
                    f"{name!r} has invalid update-types value {ut!r}; "
                    f"valid: {sorted(VALID_UPDATE_TYPES)}"
                )
