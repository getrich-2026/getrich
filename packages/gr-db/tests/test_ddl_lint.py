"""Tests for the opt-in migration comment coverage guard."""

from __future__ import annotations

from pathlib import Path

from gr_db.docs.ddl_lint import changed_migrations, comment_violations


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
