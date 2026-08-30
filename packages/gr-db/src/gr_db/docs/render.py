"""把数据字典模型渲染为离线单文件 HTML 或 JSON。"""

from __future__ import annotations

import html
import json
from dataclasses import asdict
from pathlib import Path
from string import Template

from .model import DatasetDoc, Dictionary, TableDoc


def _escape(value: object | None) -> str:
    return html.escape("" if value is None else str(value))


def _size(value: int | None) -> str:
    if value is None:
        return "—"
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return "—"


def _table_card(table: TableDoc) -> str:
    search_terms = (table.qualified + " " + " ".join(c.name for c in table.columns)).lower()
    columns = "".join(
        f"<tr><td><code>{_escape(column.name)}</code></td><td>{_escape(column.data_type)}</td>"
        f"<td>{'YES' if column.nullable else 'NO'}</td><td>{_escape(column.default)}</td>"
        f"<td>{_escape(column.comment)}</td></tr>"
        for column in table.columns
    )
    facts = [
        f"行数估算：{_escape(table.row_estimate)}" if table.row_estimate is not None else "",
        f"大小：{_size(table.total_bytes)}" if table.total_bytes is not None else "",
        f"引擎：{_escape(table.engine)}" if table.engine else "",
        f"超表维度：{_escape(table.hypertable)}" if table.hypertable else "",
        f"写入方：{_escape(', '.join(table.providers))}" if table.providers else "",
        f"数据集：{_escape(', '.join(table.datasets))}" if table.datasets else "",
    ]
    details = "".join(f"<li>{item}</li>" for item in facts if item)
    extra = "".join(f"<li>{_escape(item)}</li>" for item in (*table.constraints, *table.indexes))
    header = (
        f'<article id="{_escape(table.qualified)}" class="card" '
        f'data-search="{_escape(search_terms)}">'
    )
    title = f"<h3><code>{_escape(table.qualified)}</code></h3>"
    comment = f"<p>{_escape(table.comment) or '无表注释'}</p>"
    columns_table = (
        "<table><thead><tr><th>列</th><th>类型</th><th>可空</th><th>默认</th><th>注释</th>"
        f"</tr></thead><tbody>{columns}</tbody></table>"
    )
    return (
        header
        + title
        + comment
        + f"<ul class=meta>{details}</ul>"
        + columns_table
        + f"<ul class=meta>{extra}</ul></article>"
    )


def _dataset_row(dataset: DatasetDoc) -> str:
    """渲染 raw 数据集表格的一行。"""
    return (
        "<tr>"
        f"<td>{_escape(dataset.provider)}</td><td>{_escape(dataset.dataset)}</td>"
        f"<td><code>{_escape(dataset.path)}</code></td>"
        f"<td>{_escape(dataset.file_count)}</td><td>{_size(dataset.total_bytes)}</td>"
        f"<td>{_escape(', '.join(dataset.targets))}</td></tr>"
    )


def render_html(dictionary: Dictionary) -> str:
    """渲染不含外部资源的数据字典 HTML。

    Time Complexity: O(t + c + f)，分别为表、列和漂移数。
    Space Complexity: O(t + c + f)。
    """
    tables = [table for schema in dictionary.schemas for table in schema.tables]
    table_count = len(tables) + len(dictionary.clickhouse_tables)
    column_count = sum(len(table.columns) for table in tables) + sum(
        len(table.columns) for table in dictionary.clickhouse_tables
    )
    commented = sum(1 for table in tables if table.comment)
    errors = sum(item.severity == "error" for item in dictionary.findings)
    warnings = sum(item.severity == "warn" for item in dictionary.findings)
    nav = "".join(
        f'<a href="#{_escape(schema.name)}">PG · {_escape(schema.name)}</a>'
        for schema in dictionary.schemas
    )
    nav += (
        '<a href="#clickhouse">ClickHouse</a><a href="#raw">Raw datasets</a>'
        '<a href="#drift">漂移</a>'
    )
    body = "".join(
        f'<section id="{_escape(schema.name)}"><h2>PostgreSQL · {_escape(schema.name)}</h2>'
        + "".join(_table_card(table) for table in schema.tables)
        + "</section>"
        for schema in dictionary.schemas
    )
    body += (
        '<section id="clickhouse"><h2>ClickHouse</h2>'
        + "".join(_table_card(table) for table in dictionary.clickhouse_tables)
        + "</section>"
    )
    raw_rows = "".join(_dataset_row(item) for item in dictionary.datasets)
    body += (
        '<section id="raw"><h2>Raw datasets</h2><table><tr><th>Provider</th>'
        "<th>Dataset</th><th>约定路径</th><th>文件数</th><th>大小</th><th>目标表</th>"
        f"</tr>{raw_rows}</table></section>"
    )
    findings = "".join(
        f'<li class="{item.severity}"><strong>{item.severity.upper()}</strong> '
        f"{_escape(item.target)}：{_escape(item.message)}</li>"
        for item in dictionary.findings
    )
    body += f'<section id="drift"><h2>漂移</h2><ul>{findings or "<li>无漂移</li>"}</ul></section>'
    stats = "".join(
        (
            f"<span class=stat>Schema {len(dictionary.schemas)}</span>",
            f"<span class=stat>表 {table_count}</span>",
            f"<span class=stat>列 {column_count}</span>",
            f"<span class=stat>PG 表注释 {commented}/{len(tables)}</span>",
            f'<span class="stat error">Error {errors}</span>',
            f'<span class="stat warn">Warn {warnings}</span>',
        )
    )
    content = (
        '<header><h1>GetRich 数据字典</h1><div class="stats">'
        + stats
        + '</div><input id="search" type="search" placeholder="搜索表名或列名">'
        + '</header><div class="layout"><nav>'
        + nav
        + "</nav><main>"
        + body
        + "</main></div>"
    )
    template = Template((Path(__file__).with_name("template.html")).read_text(encoding="utf-8"))
    return template.substitute(content=content)


def render_json(dictionary: Dictionary) -> str:
    """把数据字典编码为供自动化断言使用的 JSON。

    Time Complexity: O(n)，n 为模型字段总数。
    Space Complexity: O(n)。
    """
    return json.dumps(asdict(dictionary), ensure_ascii=False, indent=2)
