"""导入版本取源码提交，文档提交不变；生产脏源码和缺失 Git 身份必须拒绝。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from gr_data.common.ricequant_specs import ContractViolationError
from gr_data.db import risk_receipts
from psycopg.pq import TransactionStatus


_SOURCE = "packages/gr-data/src/gr_data/db/risk_receipts.py"
_DDL = "packages/gr-db/src/gr_db/ddl/postgres/001_fixture.sql"


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "-C",
            str(root),
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    ).stdout.strip()


def commit(root: Path, path: str, content: str) -> str:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    git(root, "add", "--", path)
    git(root, "commit", "-m", "test: fixture")
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def version_repo(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    commit(root, _SOURCE, "# fixture\n")
    commit(root, _DDL, "-- fixture\n")
    monkeypatch.setattr(risk_receipts, "__file__", str(root / _SOURCE))
    risk_receipts._checkout_root.cache_clear()
    risk_receipts._bound_importer_commit.cache_clear()
    yield root
    risk_receipts._checkout_root.cache_clear()
    risk_receipts._bound_importer_commit.cache_clear()


def fresh_version() -> str:
    # 模拟新进程，避免缓存使“文档提交不变”测试成为空断言。
    risk_receipts._bound_importer_commit.cache_clear()
    return risk_receipts.get_importer_version(require_clean=True)


def test_version_uses_latest_source_commit_not_documentation_head(version_repo):
    root = version_repo
    first = fresh_version()
    assert first == git(root, "rev-parse", "HEAD") and len(first) == 40
    docs = commit(root, "docs/notes.md", "documentation only\n")
    assert docs != first
    assert risk_receipts.get_importer_version(require_clean=True) == first
    assert fresh_version() == first
    source = commit(root, _SOURCE, "# changed importer\n")
    assert fresh_version() == source != first
    ddl = commit(root, _DDL, "-- changed ddl\n")
    assert fresh_version() == ddl != source


@pytest.mark.parametrize(
    ("path", "stage"),
    [
        (_SOURCE, False),
        (_SOURCE, True),
        (_DDL, False),
        ("packages/gr-data/src/gr_data/new_module.py", False),
        ("packages/gr-db/src/gr_db/ddl/postgres/new.sql", False),
    ],
)
def test_production_rechecks_dirty_sources_even_after_version_is_cached(version_repo, path, stage):
    root = version_repo
    version = risk_receipts.get_importer_version(require_clean=True)
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("changed\n")
    if stage:
        git(root, "add", "--", path)
    with pytest.raises(ContractViolationError, match="requires committed importer source"):
        risk_receipts.get_importer_version(require_clean=True)
    assert risk_receipts.get_importer_version() == version


def test_dirty_documentation_does_not_change_importer_source_identity(version_repo):
    version = risk_receipts.get_importer_version(require_clean=True)
    (version_repo / "NOTES.md").write_text("uncommitted documentation\n")
    assert risk_receipts.get_importer_version(require_clean=True) == version


@pytest.mark.parametrize(
    "failure", [FileNotFoundError("git unavailable"), subprocess.TimeoutExpired("git", timeout=5)]
)
def test_missing_or_hanging_git_fails_closed(version_repo, monkeypatch, failure):
    risk_receipts.get_importer_version(require_clean=True)

    def failed(*args, **kwargs):
        raise failure

    monkeypatch.setattr(risk_receipts.subprocess, "run", failed)
    with pytest.raises(ContractViolationError, match="accessible Git checkout"):
        risk_receipts.get_importer_version()


def test_checkout_without_source_commit_fails_closed(tmp_path, monkeypatch):
    root = tmp_path / "empty-checkout"
    root.mkdir()
    git(root, "init")
    module = root / _SOURCE
    module.parent.mkdir(parents=True)
    module.write_text("# uncommitted\n")
    monkeypatch.setattr(risk_receipts, "__file__", str(module))
    risk_receipts._checkout_root.cache_clear()
    risk_receipts._bound_importer_commit.cache_clear()
    with pytest.raises(ContractViolationError):
        risk_receipts.get_importer_version()
    risk_receipts._checkout_root.cache_clear()
    risk_receipts._bound_importer_commit.cache_clear()


def test_production_preflight_rejects_dirty_before_database_transaction(version_repo):
    (version_repo / _SOURCE).write_text("# dirty\n")
    conn = SimpleNamespace(info=SimpleNamespace(transaction_status=TransactionStatus.IDLE))
    options = SimpleNamespace(purpose="production")
    with pytest.raises(ContractViolationError, match="requires committed importer source"):
        risk_receipts.prepare_capture(conn, options)


@pytest.mark.parametrize("path", [_SOURCE, _DDL])
@pytest.mark.parametrize("require_clean", [False, True])
def test_clean_source_commit_change_requires_process_restart(version_repo, path, require_clean):
    first = risk_receipts.get_importer_version(require_clean=True)
    second = commit(version_repo, path, "new committed source\n")
    assert second != first
    assert git(version_repo, "status", "--porcelain") == ""
    with pytest.raises(ContractViolationError, match="source commit changed; restart"):
        risk_receipts.get_importer_version(require_clean=require_clean)
    # 明确模拟进程重启后才能绑定新提交，而非在运行中的进程自动改标签。
    assert fresh_version() == second
