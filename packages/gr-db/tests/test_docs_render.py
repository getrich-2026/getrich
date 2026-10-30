"""Tests for the offline HTML and JSON dictionary renderers."""

from __future__ import annotations

from gr_db.docs.model import ColumnDoc, DatasetDoc, Dictionary, DriftFinding, SchemaDoc, TableDoc
from gr_db.docs.render import _size, render_html, render_json


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


def test_render_html_shows_storage_layout_and_makes_rows_searchable() -> None:
    """压缩状态与 CH 分区/排序键要展示；raw 行和漂移条目也参与搜索。"""
    dictionary = Dictionary(
        schemas=(
            SchemaDoc(
                "market",
                (
                    TableDoc(
                        schema="market", name="stock_bar_1d", hypertable="dt", compression="enabled"
                    ),
                ),
            ),
        ),
        clickhouse_tables=(
            TableDoc(
                schema="factor",
                name="factors_long",
                engine="MergeTree",
                partition_key="toYYYYMM(dt)",
                sorting_key="factor, symbol, dt",
            ),
        ),
        datasets=(
            DatasetDoc("tushare", "daily", "/raw/tushare/daily", targets=("market.stock_bar_1d",)),
        ),
        findings=(DriftFinding("warn", "缺少注释", "market.Stock_bar_1d"),),
    )

    output = render_html(dictionary)

    assert "压缩：enabled" in output
    assert "分区键：toYYYYMM(dt)" in output
    assert "排序键：factor, symbol, dt" in output
    assert '<tr data-search="tushare daily market.stock_bar_1d">' in output
    assert 'data-search="market.stock_bar_1d"><strong>WARN' in output


def test_size_formats_unit_boundaries() -> None:
    assert _size(None) == "—"
    assert _size(1023) == "1023.0 B"
    assert _size(1024) == "1.0 KiB"
    assert _size(5 << 40) == "5.0 TiB"
    assert _size(2048 << 40) == "2048.0 TiB"
