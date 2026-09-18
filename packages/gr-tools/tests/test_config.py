"""环境加载的来源、隔离与导入副作用回归。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from gr_tools.config import Environment, SettingsError, find_project_root, load_environment


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
