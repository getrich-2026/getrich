"""Tests for the opt-in migration comment coverage guard."""

from __future__ import annotations

import subprocess
from pathlib import Path

from gr_db.ddl_lint import changed_migrations, comment_violations


def test_comment_violations_accepts_comments_from_any_migration(tmp_path: Path) -> None:
    """后续迁移补的注释也应覆盖早期建表迁移。"""
    changed = tmp_path / "040_demo.sql"
    changed.write_text(
        """
        CREATE TABLE IF NOT EXISTS app.demo (
            id UUID PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL,
            name TEXT NOT NULL
        );
        """,
        encoding="utf-8",
    )
    (tmp_path / "041_comments.sql").write_text(
        """
        COMMENT ON TABLE app.demo IS '演示表';
        COMMENT ON COLUMN app.demo.name IS '名称';
        """,
        encoding="utf-8",
    )

    assert comment_violations([changed], tmp_path) == []


def test_comment_violations_rejects_missing_required_column_comment(tmp_path: Path) -> None:
    """非自明列没有 COMMENT ON COLUMN 时必须失败。"""
    changed = tmp_path / "040_demo.sql"
    changed.write_text(
        "CREATE TABLE IF NOT EXISTS app.demo (id UUID, payload JSONB);",
        encoding="utf-8",
    )

    violations = comment_violations([changed], tmp_path)

    assert any("app.demo 缺少 COMMENT ON TABLE" in item for item in violations)
    assert any("app.demo.payload 缺少 COMMENT ON COLUMN" in item for item in violations)


def test_comment_violations_rejects_uncommented_alter_table_column(tmp_path: Path) -> None:
    """ALTER TABLE 新增的业务列也必须有注释。"""
    changed = tmp_path / "040_demo.sql"
    changed.write_text(
        "ALTER TABLE app.demo ADD COLUMN IF NOT EXISTS payload JSONB;",
        encoding="utf-8",
    )

    violations = comment_violations([changed], tmp_path)

    assert violations == [f"{changed}: app.demo.payload 缺少 COMMENT ON COLUMN"]


def test_comment_violations_accepts_multi_column_alter_table_comments(tmp_path: Path) -> None:
    """同一 ALTER TABLE 的多个新增列均应检查，审计字段可豁免。"""
    changed = tmp_path / "040_demo.sql"
    changed.write_text(
        """
        ALTER TABLE app.demo
            ADD COLUMN IF NOT EXISTS payload JSONB,
            ADD COLUMN IF NOT EXISTS status TEXT,
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
        """,
        encoding="utf-8",
    )
    (tmp_path / "041_comments.sql").write_text(
        """
        COMMENT ON COLUMN app.demo.payload IS '载荷';
        COMMENT ON COLUMN app.demo.status IS '状态';
        """,
        encoding="utf-8",
    )

    assert comment_violations([changed], tmp_path) == []


def test_changed_migrations_skips_when_base_ref_is_missing(tmp_path: Path) -> None:
    """本地没有 remote/base ref 时门禁应给出警告并保持成功。"""
    changed, warning = changed_migrations(tmp_path, tmp_path, "origin/not-present")

    assert changed == []
    assert warning is not None


def test_comment_violations_keeps_double_dash_inside_string_literals(tmp_path: Path) -> None:
    """注释字符串里的 -- 不能被当成 SQL 注释截断，否则后续 COMMENT ON 都匹配不上。"""
    changed = tmp_path / "040_demo.sql"
    changed.write_text(
        """
        CREATE TABLE IF NOT EXISTS app.demo (
            id UUID PRIMARY KEY,  -- 主键，单引号 ' 出现在注释里不影响
            status TEXT NOT NULL CHECK (status IN ('a,b', 'c(')),
            name TEXT NOT NULL
        );
        COMMENT ON TABLE app.demo IS '演示 -- 表';
        COMMENT ON COLUMN app.demo.status IS '状态';
        COMMENT ON COLUMN app.demo.name IS '名称';
        """,
        encoding="utf-8",
    )

    assert comment_violations([changed], tmp_path) == []


def test_changed_migrations_ignores_deleted_files(tmp_path: Path) -> None:
    """删除迁移不应进入检查列表，否则读取文件时门禁崩溃。"""

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    ddl_dir = tmp_path / "ddl"
    ddl_dir.mkdir()
    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "test")
    (ddl_dir / "001_old.sql").write_text("SELECT 1;", encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "base")
    git("tag", "base")
    (ddl_dir / "001_old.sql").unlink()
    (ddl_dir / "002_new.sql").write_text("SELECT 2;", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "change")

    changed, warning = changed_migrations(tmp_path, ddl_dir, "base")

    assert warning is None
    assert changed == [ddl_dir / "002_new.sql"]
