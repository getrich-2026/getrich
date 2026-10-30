"""Tests for data dictionary provenance and contract drift checks."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gr_data.common.contracts.base import TableContract
from gr_db.docs import build_dictionary
from gr_db.docs.model import ColumnDoc, SchemaDoc, TableDoc
from gr_db.docs.provenance import discover_datasets, enrich_provenance, fetch_ownership
from psycopg import errors as pg_errors


def _module(registry: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(REGISTRY=registry)


def test_enrich_provenance_reports_missing_contract_column_and_ownership_conflict() -> None:
    """契约列或运行时 provider 不一致必须成为 error。"""
    importer = SimpleNamespace(
        CONTRACT=TableContract("market", "bars", ("dt", "close"), ("dt",)),
    )
    schemas = (
        SchemaDoc(
            "market",
            (
                TableDoc(
                    schema="market",
                    name="bars",
                    columns=(ColumnDoc("dt", "date", False),),
                ),
            ),
        ),
    )

    with patch(
        "gr_db.docs.provenance.importlib.import_module", return_value=_module({"bars": importer})
    ):
        _schemas, findings = enrich_provenance(schemas, {"market.bars": ("unknown", "ingest")})

    assert {(item.severity, item.message) for item in findings} >= {
        ("error", "契约列 close 在活库中不存在"),
        ("error", "运行时归属 provider=unknown 与注册表不一致"),
    }


def test_enrich_provenance_tolerates_importer_without_contract() -> None:
    """没有 CONTRACT 的 importer 不得让字典生成中断。"""
    with patch(
        "gr_db.docs.provenance.importlib.import_module", return_value=_module({"raw_only": object})
    ):
        schemas, findings = enrich_provenance((), {})

    assert schemas == ()
    assert findings == ()


def test_build_dictionary_for_clickhouse_does_not_run_postgres_drift_checks() -> None:
    """仅生成 ClickHouse 字典时，不能把缺失的 PG 表误报为漂移。"""
    clickhouse_client = object()
    with (
        patch("gr_db.docs.introspect_postgres") as introspect_postgres,
        patch("gr_db.docs.fetch_ownership") as fetch_ownership,
        patch("gr_db.docs.enrich_provenance") as enrich_provenance,
        patch("gr_db.docs.introspect_clickhouse", return_value=()) as introspect_clickhouse,
        patch("gr_db.docs.discover_datasets", return_value=()),
        patch("gr_db.docs.load_registry", return_value=()),
    ):
        dictionary = build_dictionary(clickhouse_client=clickhouse_client)

    introspect_postgres.assert_not_called()
    fetch_ownership.assert_not_called()
    enrich_provenance.assert_not_called()
    introspect_clickhouse.assert_called_once_with(clickhouse_client)
    assert dictionary.schemas == ()
    assert dictionary.findings == ()


def _bars_schema(*columns: ColumnDoc, comment: str | None = "日线") -> tuple[SchemaDoc, ...]:
    return (
        SchemaDoc(
            "market", (TableDoc(schema="market", name="bars", columns=columns, comment=comment),)
        ),
    )


def test_enrich_provenance_aggregates_missing_column_comments_and_exempts_audit_columns() -> None:
    """缺注释的列按表汇总为一条 warn，主键与审计列不计入。"""
    schemas = _bars_schema(
        ColumnDoc("id", "bigint", False),
        ColumnDoc("updated_at", "timestamptz", False),
        ColumnDoc("close", "numeric", True),
        ColumnDoc("open", "numeric", True),
        ColumnDoc("dt", "date", False, comment="交易日"),
    )

    _schemas, findings = enrich_provenance(schemas, {}, registry=())

    assert [item.message for item in findings] == ["2 列缺少 COMMENT ON：close, open"]


def test_enrich_provenance_skips_ownership_checks_when_table_is_missing() -> None:
    """ops.table_ownership 尚未迁移时只给一条 warn，不再逐表报未登记。"""
    importer = SimpleNamespace(CONTRACT=TableContract("market", "bars", ("dt",), ("dt",)))
    schemas = _bars_schema(ColumnDoc("dt", "date", False, comment="交易日"))

    output, findings = enrich_provenance(schemas, None, registry=(("tushare", "bars", importer),))

    assert [(item.severity, item.target) for item in findings] == [("warn", "ops.table_ownership")]
    assert output[0].tables[0].providers == ("tushare",)


class _FailingConnection:
    def cursor(self) -> _FailingConnection:
        return self

    def __enter__(self) -> _FailingConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, _sql: str) -> None:
        raise pg_errors.UndefinedTable('relation "ops.table_ownership" does not exist')


def test_fetch_ownership_returns_none_when_table_is_missing() -> None:
    """新库缺少归属表时降级而非让字典生成失败。"""
    assert fetch_ownership(_FailingConnection()) is None


def test_discover_datasets_counts_only_regular_files(tmp_path: Path) -> None:
    """目录不计入文件数；目录不存在时统计为未知。"""
    importer = SimpleNamespace(CONTRACT=TableContract("market", "bars", ("dt",), ("dt",)))
    registry = (("tushare", "bars", importer), ("tushare", "absent", object()))
    dataset_dir = tmp_path / "tushare" / "bars" / "year=2026"
    dataset_dir.mkdir(parents=True)
    (dataset_dir / "part-0.parquet").write_bytes(b"x" * 10)
    (dataset_dir / "part-1.parquet").write_bytes(b"x" * 5)

    present, absent = discover_datasets(tmp_path, registry=registry)

    assert (present.file_count, present.total_bytes, present.targets) == (2, 15, ("market.bars",))
    assert (absent.file_count, absent.total_bytes, absent.targets) == (None, None, ())
