"""环境加载的来源、隔离与导入副作用回归。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from gr_tools.config import (
    Environment,
    LoggingConfig,
    SettingsError,
    find_project_root,
    load_environment,
    parse_bool,
)


def test_environment_precedence_snapshot_and_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("EXTERNAL_ONLY", "kept")
    local = tmp_path / ".env"
    local.write_text("A=file\nB=${A}\nEMPTY=filled\nDEFAULT=${MISSING:-fallback}\n")
    before = dict(os.environ)
    env = load_environment(root=tmp_path, environ={"A": "process", "EMPTY": ""})
    assert env.values == {"A": "process", "B": "process", "EMPTY": "", "DEFAULT": "fallback"}
    assert dict(os.environ) == before
    assert env.env_file == local
    with pytest.raises(TypeError):
        env.values["A"] = "changed"


def test_explicit_file_user_fallback_and_no_creation(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    env = load_environment(root=project, environ={})
    assert env.env_file is None
    assert not home.exists()
    user_env = home / ".config/getrich/.env"
    user_env.parent.mkdir(parents=True)
    user_env.write_text("A=user\n")
    assert load_environment(root=project, environ={}).values["A"] == "user"
    (project / ".env").write_text("A=project\n")
    assert load_environment(root=project, environ={}).values["A"] == "project"
    explicit = tmp_path / "explicit.env"
    explicit.write_text("A=explicit\n")
    assert load_environment(explicit, root=project, environ={}).values["A"] == "explicit"
    with pytest.raises(SettingsError, match="does not exist"):
        load_environment(tmp_path / "absent", root=project, environ={})


def test_workspace_root_from_member_and_file(tmp_path, monkeypatch):
    monkeypatch.delenv("GETRICH_ROOT", raising=False)
    (tmp_path / "pyproject.toml").write_text("[tool.uv.workspace]\nmembers = ['packages/*']\n")
    member = tmp_path / "packages/member"
    member.mkdir(parents=True)
    module = member / "pyproject.toml"
    module.write_text("[project]\nname = 'member'\n")
    assert find_project_root(member) == tmp_path
    assert find_project_root(module) == tmp_path
    monkeypatch.chdir(member)
    assert find_project_root() == tmp_path
    monkeypatch.setenv("GETRICH_ROOT", str(member))
    assert find_project_root() == member


def test_install_is_explicit_and_does_not_override_process(tmp_path, monkeypatch):
    monkeypatch.delenv("CONFIG_TEST_NEW", raising=False)
    monkeypatch.setenv("CONFIG_TEST_OLD", "process")
    (tmp_path / ".env").write_text("CONFIG_TEST_NEW=file\nCONFIG_TEST_OLD=file\n")
    load_environment(root=tmp_path)
    assert "CONFIG_TEST_NEW" not in os.environ
    load_environment(root=tmp_path, install=True)
    assert os.environ["CONFIG_TEST_NEW"] == "file"
    assert os.environ["CONFIG_TEST_OLD"] == "process"
    monkeypatch.delenv("CONFIG_TEST_NEW")


def test_environment_repr_hides_values(tmp_path):
    assert "sentinel-secret" not in repr(Environment(tmp_path, {"PASSWORD": "sentinel-secret"}))


def test_environment_snapshot_is_independent_of_later_process_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_TEST_SNAPSHOT", "first")
    (tmp_path / ".env").touch()
    first = load_environment(root=tmp_path)
    monkeypatch.setenv("CONFIG_TEST_SNAPSHOT", "second")
    second = load_environment(root=tmp_path)
    assert first.values["CONFIG_TEST_SNAPSHOT"] == "first"
    assert second.values["CONFIG_TEST_SNAPSHOT"] == "second"


def test_log_file_expands_home_before_resolving_relative_path(tmp_path: Path) -> None:
    home = Path.home()
    config = LoggingConfig.from_env(tmp_path, {"LOG_FILE": "~/logs/app.log"})
    assert config.file_path == home / "logs/app.log"


@pytest.mark.parametrize("name", ["LOG_LEVEL", "LOG_JSON"])
def test_invalid_log_options_raise_settings_error(tmp_path: Path, name: str) -> None:
    with pytest.raises(SettingsError, match=name) as error:
        LoggingConfig.from_env(tmp_path, {name: "invalid-sentinel"})
    assert "invalid-sentinel" not in str(error.value)


@pytest.mark.parametrize(
    "member_project",
    [
        '# Example: [tool.uv.workspace]\n[project]\nname = "member"\n',
        '[project\nname = "member"\n',
        'tool = "not-a-table"\n',
        '[tool]\nuv = "not-a-table"\n',
        '[tool.uv]\nworkspace = "not-a-table"\n',
    ],
)
def test_workspace_search_skips_invalid_or_non_workspace_projects(
    tmp_path: Path, member_project: str
) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.uv.workspace]\n", encoding="utf-8")
    member = tmp_path / "member"
    member.mkdir()
    (member / "pyproject.toml").write_text(member_project, encoding="utf-8")
    assert find_project_root(member, environ={}) == tmp_path


def test_workspace_search_skips_unreadable_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.uv.workspace]\n", encoding="utf-8")
    member = tmp_path / "member"
    member.mkdir()
    project = member / "pyproject.toml"
    project.write_text("[tool.uv.workspace]\n", encoding="utf-8")
    original_open = Path.open

    def guarded_open(path: Path, *args, **kwargs):
        if path == project:
            raise PermissionError("test read denied")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    assert find_project_root(member, environ={}) == tmp_path


def test_workspace_search_skips_invalid_utf8_and_falls_back_to_git(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_bytes(b"\xff")
    (tmp_path / ".git").mkdir()
    member = tmp_path / "member"
    member.mkdir()
    assert find_project_root(member, environ={}) == tmp_path


def test_environment_root_precedence(tmp_path: Path) -> None:
    override = tmp_path / "override"
    explicit = tmp_path / "explicit"
    for directory in (override, explicit):
        directory.mkdir()
        (directory / ".env").touch()
    source = {"GETRICH_ROOT": str(override)}
    assert load_environment(environ=source).root == override
    assert load_environment(root=explicit, environ=source).root == explicit


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, False),
        ("", False),
        ("true", True),
        ("True", True),
        ("1", True),
        ("yes", True),
        ("YES", True),
        ("on", True),
        ("ON", True),
        ("false", False),
        ("FALSE", False),
        ("0", False),
        ("no", False),
        ("NO", False),
        ("off", False),
        ("Off", False),
    ],
)
def test_boolean_parser_and_log_json_share_rules(
    tmp_path: Path, value: str | None, expected: bool
) -> None:
    assert parse_bool(value, name="FEATURE_FLAG") is expected
    source = {} if value is None else {"LOG_JSON": value}
    assert LoggingConfig.from_env(tmp_path, source).json_format is expected


@pytest.mark.parametrize("value", ["tru", "invalid-sentinel", " true "])
def test_boolean_parser_rejects_unknown_values_without_disclosing_them(value: str) -> None:
    with pytest.raises(SettingsError) as error:
        parse_bool(value, name="FEATURE_FLAG")
    assert str(error.value) == "FEATURE_FLAG must be a boolean"
    assert value not in str(error.value)


@pytest.mark.parametrize("app_env", ["dev", "prod", "PROD"])
def test_invalid_strict_mode_is_rejected_even_in_production(tmp_path: Path, app_env: str) -> None:
    environment = Environment(tmp_path, {"STRICT_MODE": "tru", "APP_ENV": app_env})
    with pytest.raises(SettingsError, match="STRICT_MODE") as error:
        _ = environment.strict
    assert "tru" not in str(error.value)


@pytest.mark.parametrize("app_env", ["prod", "PROD", "Prod"])
def test_production_enables_strict_mode_case_insensitively(tmp_path: Path, app_env: str) -> None:
    assert Environment(tmp_path, {"APP_ENV": app_env, "STRICT_MODE": "0"}).strict


@pytest.mark.parametrize(
    ("source", "expected"),
    [({}, False), ({"APP_ENV": "dev"}, False), ({"STRICT_MODE": "ON"}, True)],
)
def test_strict_mode_defaults_and_explicit_enable(
    tmp_path: Path, source: dict[str, str], expected: bool
) -> None:
    assert Environment(tmp_path, source).strict is expected
