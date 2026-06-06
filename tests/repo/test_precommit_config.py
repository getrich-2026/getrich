"""Smoke tests for ``.pre-commit-config.yaml``.

Why this matters
----------------
The config file pins third-party revs (pre-commit-hooks,
ruff-pre-commit, conventional-pre-commit). When the revs
go stale, the hooks stop receiving fixes and may even
fail to install on Python 3.13+. We catch a stale config
before it bites a developer with::

    $ pre-commit run --all-files
    An unexpected error has occurred: ...

These tests are intentionally cheap and self-contained:
they read the file as text + parse it as YAML, and assert
the structural invariants the rest of the repo relies on.

They do NOT run pre-commit itself — that's the whole point
of pre-commit, and a sandbox that can't install the hooks
(common on the Windows build agent) shouldn't fail the
unit-test suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = REPO_ROOT / ".pre-commit-config.yaml"


@pytest.fixture(scope="module")
def cfg() -> dict:
    """Parse the config once for the whole module.

    We do this with PyYAML rather than calling
    ``pre-commit load-config`` so the test works in a
    sandbox that doesn't have pre-commit installed.
    """
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. File presence + well-formedness
# ---------------------------------------------------------------------------


def test_config_file_exists() -> None:
    """The pre-commit config must be at the repo root.

    Pre-commit looks for ``.pre-commit-config.yaml`` in the
    repo root by default; placing it anywhere else requires
    a per-developer config override.
    """
    assert CONFIG.is_file(), (
        f"missing config at {CONFIG.relative_to(REPO_ROOT)}; "
        f"pre-commit requires it at the repo root"
    )


def test_config_parses_as_yaml() -> None:
    """Pre-commit-hooks' check-yaml requires valid YAML.

    We don't run check-yaml itself because that would
    shell out; a PyYAML parse is good enough to catch
    syntax errors.
    """
    data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert isinstance(data, dict), (
        f"top-level YAML must be a mapping, got {type(data).__name__}"
    )
    assert "repos" in data, "missing required `repos` key"


# ---------------------------------------------------------------------------
# 2. Structural invariants
# ---------------------------------------------------------------------------


def test_repos_is_nonempty_list(cfg: dict) -> None:
    """A pre-commit config without repos is a no-op."""
    repos = cfg["repos"]
    assert isinstance(repos, list)
    assert len(repos) >= 1, "pre-commit config has no repos — useless"


def test_every_hook_has_required_fields(cfg: dict) -> None:
    """Pre-commit rejects a hook missing `id` or `stages` (or default)."""
    for repo in cfg["repos"]:
        # Same local-repo detection as in the other test.
        is_local = repo.get("repo") in (None, "local")
        repo_label = repo.get("repo") or "local"
        for hook in repo.get("hooks", []):
            assert "id" in hook, (
                f"hook in repo {repo_label!r} missing required `id` field"
            )
            # `language` defaults to "system" for local repos;
            # for remote repos it must be the hook's default.
            if is_local:
                assert hook.get("language") in (None, "system"), (
                    f"local hook {hook['id']!r} must use language=system "
                    f"(or omit it), got {hook.get('language')!r}"
                )


def test_hooks_have_unique_ids(cfg: dict) -> None:
    """Hook ids must be unique across the whole config — pre-commit
    refuses to install a config with a collision.
    """
    seen: dict[str, str] = {}
    for repo in cfg["repos"]:
        for hook in repo.get("hooks", []):
            hid = hook["id"]
            if hid in seen:
                pytest.fail(
                    f"hook id {hid!r} is declared twice: "
                    f"in {seen[hid]!r} and in {repo.get('repo', 'local')!r}"
                )
            seen[hid] = repo.get("repo") or "local"


def test_remote_repos_pin_a_rev(cfg: dict) -> None:
    """Every remote repo entry must have an exact rev (SHA or tag).

    Pinning to ``main`` is forbidden by pre-commit itself; pinning
    to a float (e.g. ``v5``) is allowed but loses reproducibility
    for major-version drift. We require an exact tag.
    """
    bad: list[str] = []
    for repo in cfg["repos"]:
        # A local repo is identified by the literal string
        # "local" (or is missing the `repo` key in some configs).
        # Neither needs a `rev`.
        if repo.get("repo") in (None, "local"):
            continue
        rev = repo.get("rev", "")
        if not rev or rev in ("main", "master", "HEAD"):
            bad.append(f"{repo['repo']}@rev={rev!r}")
    assert not bad, (
        "the following remote repos have unpinned revs (pre-commit "
        "will refuse to install):\n  " + "\n  ".join(bad)
    )


# ---------------------------------------------------------------------------
# 3. CI parity — every CI step we want to mirror locally must appear
# ---------------------------------------------------------------------------


EXPECTED_HOOK_IDS = {
    # ruff
    "ruff",
    "ruff-format",
    # silent-fail scanner
    "silent-fails-scan",
    # migration linters
    "pg-migrations-lint",
    "clickhouse-migrations-lint",
    # frontend
    "eslint",
    "tsc-no-emit",
    # commit message
    "conventional-pre-commit",
}


def test_required_hooks_are_present(cfg: dict) -> None:
    """The hooks we care about must be in the config.

    If a hook is removed accidentally, the corresponding CI
    job may also be removed (or its name changed) — that
    should be a conscious decision, not a side effect of an
    unrelated edit.
    """
    actual = {
        hook["id"]
        for repo in cfg["repos"]
        for hook in repo.get("hooks", [])
    }
    missing = EXPECTED_HOOK_IDS - actual
    assert not missing, (
        "the following hook ids must stay in the pre-commit config: "
        f"{sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# 4. exclude patterns parse as valid regex
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("repo_idx,hook_idx", [
    (i, j)
    for i, r in enumerate(yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["repos"])
    for j, _ in enumerate(r.get("hooks", []))
])
def test_exclude_patterns_are_valid_regex(cfg: dict, repo_idx: int, hook_idx: int) -> None:
    """Pre-commit-hooks compiles each ``exclude`` as a regex;
    an invalid pattern breaks the install. Catch the typo
    before the developer does.
    """
    import re

    hook = cfg["repos"][repo_idx]["hooks"][hook_idx]
    exclude = hook.get("exclude")
    if exclude is None:
        return
    # ``exclude`` is a string in the YAML; multiline regexes
    # are wrapped in (?x) for readability.
    try:
        re.compile(exclude)
    except re.error as e:
        pytest.fail(
            f"hook {hook['id']!r} has invalid exclude regex "
            f"({exclude!r}): {e}"
        )


# ---------------------------------------------------------------------------
# 5. Hook that calls a local script must reference a file that exists
# ---------------------------------------------------------------------------


LOCAL_HOOK_SCRIPTS = [
    # (hook_id, expected_path_relative_to_repo_root)
    ("silent-fails-scan", "scripts/find_silent_fails.py"),
    ("pg-migrations-lint", "scripts/lint_migrations.py"),
    ("clickhouse-migrations-lint", "scripts/lint_clickhouse_migrations.py"),
]


@pytest.mark.parametrize("hook_id,script_relpath", LOCAL_HOOK_SCRIPTS)
def test_local_hook_script_exists(hook_id: str, script_relpath: str) -> None:
    """A local hook whose `entry` is a script path is useless
    if the script doesn't exist. This test catches the
    case where someone renames a script but forgets to
    update the pre-commit config.
    """
    path = REPO_ROOT / script_relpath
    assert path.is_file(), (
        f"local hook {hook_id!r} references {script_relpath}, "
        f"but that file is missing"
    )
