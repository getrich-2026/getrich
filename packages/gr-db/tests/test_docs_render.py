"""Tests for the offline HTML and JSON dictionary renderers."""

from __future__ import annotations

from gr_db.docs.model import ColumnDoc, Dictionary, DriftFinding, SchemaDoc, TableDoc
from gr_db.docs.render import render_html, render_json


def test_render_html_is_self_contained_and_escapes_catalog_comments() -> None:
    """DDL 注释中的 HTML 不能改变生成页面的 DOM。"""
    dictionary = Dictionary(
        schemas=(
            SchemaDoc(
                "market",
                (
                    TableDoc(
                        schema="market",
                        name="stock_bar_1d",
                        comment='注释 <img src="x">',
                        columns=(ColumnDoc("close", "numeric", False, comment="收盘 <值>"),),
                    ),
                ),
            ),
        ),
        findings=(DriftFinding("warn", "缺少注释", "market.stock_bar_1d"),),
    )

    output = render_html(dictionary)

    assert "market.stock_bar_1d" in output
    assert "&lt;img src=&quot;x&quot;&gt;" in output
    assert "&lt;值&gt;" in output
    assert "http://" not in output
    assert "https://" not in output
    assert 'id="search"' in output
    assert '"schemas"' in render_json(dictionary)
