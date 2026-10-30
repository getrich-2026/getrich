"""新增迁移的 PostgreSQL 注释覆盖率检查。"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


_CREATE_TABLE = re.compile(
    r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\s*\((.*?)\)\s*;",
    re.IGNORECASE | re.DOTALL,
)
_ALTER_TABLE = re.compile(
    r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?"
    r"([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\s+(.*?);",
    re.IGNORECASE | re.DOTALL,
)
_ADD_COLUMN = re.compile(
    r"\s*ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][\w]*)\b",
    re.IGNORECASE,
)
_COMMENT_TABLE = re.compile(
    r"COMMENT\s+ON\s+TABLE\s+([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\s+IS\s+", re.IGNORECASE
)
_COMMENT_COLUMN = re.compile(
    r"COMMENT\s+ON\s+COLUMN\s+([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\s+IS\s+",
    re.IGNORECASE,
)
SELF_EXPLANATORY_COLUMNS = frozenset({"id", "created_at", "updated_at"})
"""自明的主键与审计列：迁移注释门禁和数据字典漂移检查共用的豁免集合。"""

# 字符串字面量排在注释前面，从左到右扫描时引号内的 -- 不会被当成注释。
_COMMENT_OR_LITERAL = re.compile(r"'(?:''|[^'])*'|--[^\n]*|/\*.*?\*/", re.DOTALL)


def _strip_sql_comments(sql: str) -> str:
    """删除 SQL 注释，保留字符串字面量原文。

    Time Complexity: O(n)，n 为 SQL 字符数。
    Space Complexity: O(n)。
    """
    return _COMMENT_OR_LITERAL.sub(
        lambda match: match.group() if match.group().startswith("'") else "", sql
    )


def _top_level_parts(definition: str) -> tuple[str, ...]:
    """按顶层逗号拆分 SQL 定义或 ALTER TABLE 动作，忽略字符串字面量内的括号与逗号。

    Time Complexity: O(n)，n 为定义字符数。
    Space Complexity: O(n)。
    """
    parts: list[str] = []
    depth = 0
    in_literal = False
    part: list[str] = []
    for char in definition + ",":
        if char == "'":
            # '' 转义会让状态连续翻转两次，结果仍正确。
            in_literal = not in_literal
        elif not in_literal:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif char == "," and depth == 0:
                parts.append("".join(part))
                part = []
                continue
        part.append(char)
    return tuple(parts)


def _columns(definition: str) -> set[str]:
    """提取 CREATE TABLE 顶层列名，跳过表级约束。

    Time Complexity: O(n)，n 为定义字符数。
    Space Complexity: O(c)，c 为列数。
    """
    columns: set[str] = set()
    for part in _top_level_parts(definition):
        match = re.match(r"\s*([A-Za-z_][\w]*)", part)
        if match and match.group(1).lower() not in {
            "constraint",
            "primary",
            "foreign",
            "unique",
            "check",
            "exclude",
        }:
            columns.add(match.group(1))
    return columns


def _added_columns(sql: str) -> tuple[tuple[str, str, str], ...]:
    """提取 ALTER TABLE 中新增的列。

    Time Complexity: O(n)，n 为 SQL 字符数。
    Space Complexity: O(a)，a 为新增列数。
    """
    columns: list[tuple[str, str, str]] = []
    for schema, table, actions in _ALTER_TABLE.findall(sql):
        for action in _top_level_parts(actions):
            match = _ADD_COLUMN.match(action)
            if match:
                columns.append((schema, table, match.group(1)))
    return tuple(columns)


def comment_violations(changed_files: list[Path], ddl_dir: Path) -> list[str]:
    """检查新增表或列及其非豁免列是否在全部 DDL 中有注释。

    Time Complexity: O(a + c)，a 为全部 DDL 字符数、c 为变更 DDL 字符数。
    Space Complexity: O(t + k)，t 为表数、k 为列数。
    """
    all_sql = "\n".join(
        _strip_sql_comments(path.read_text(encoding="utf-8")) for path in ddl_dir.glob("*.sql")
    )
    table_comments = {(schema, table) for schema, table in _COMMENT_TABLE.findall(all_sql)}
    column_comments = {
        (schema, table, column) for schema, table, column in _COMMENT_COLUMN.findall(all_sql)
    }
    violations: list[str] = []
    for path in changed_files:
        sql = _strip_sql_comments(path.read_text(encoding="utf-8"))
        for schema, table, definition in _CREATE_TABLE.findall(sql):
            if (schema, table) not in table_comments:
                violations.append(f"{path}: {schema}.{table} 缺少 COMMENT ON TABLE")
            for column in sorted(_columns(definition) - SELF_EXPLANATORY_COLUMNS):
                if (schema, table, column) not in column_comments:
                    violations.append(f"{path}: {schema}.{table}.{column} 缺少 COMMENT ON COLUMN")
        for schema, table, column in _added_columns(sql):
            if (
                column not in SELF_EXPLANATORY_COLUMNS
                and (schema, table, column) not in column_comments
            ):
                violations.append(f"{path}: {schema}.{table}.{column} 缺少 COMMENT ON COLUMN")
    return violations


def changed_migrations(
    repo_root: Path, ddl_dir: Path, base_ref: str
) -> tuple[list[Path], str | None]:
    """取得相对 base ref 新增、修改或改名的 PostgreSQL 迁移。

    只比较已提交的 ``base_ref...HEAD``，工作区未提交的迁移不在检查范围内；
    已删除的文件被过滤，避免后续读取失败。git 或 base ref 不可用时返回警告而非失败。

    Time Complexity: O(n)，n 为 git 输出中的文件数。
    Space Complexity: O(n)。
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=AMR", f"{base_ref}...HEAD"],
            cwd=repo_root,
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return [], f"无法比较 base ref {base_ref}，跳过注释覆盖检查"
    files = [repo_root / line for line in result.stdout.splitlines()]
    return [path for path in files if path.parent == ddl_dir and path.suffix == ".sql"], None
