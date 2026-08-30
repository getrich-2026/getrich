"""Tests for data dictionary provenance and contract drift checks."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from gr_data.common.contracts.base import TableContract
from gr_db.docs import build_dictionary
from gr_db.docs.model import ColumnDoc, SchemaDoc, TableDoc
from gr_db.docs.provenance import enrich_provenance


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
    ):
        dictionary = build_dictionary(clickhouse_client=clickhouse_client)

    introspect_postgres.assert_not_called()
    fetch_ownership.assert_not_called()
    enrich_provenance.assert_not_called()
    introspect_clickhouse.assert_called_once_with(clickhouse_client)
    assert dictionary.schemas == ()
    assert dictionary.findings == ()
