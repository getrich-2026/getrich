from __future__ import annotations

from getrich_data_import.db.schema_check import SchemaCheckResult


def test_schema_check_result_ok_requires_all_empty() -> None:
    assert SchemaCheckResult((), (), ()).ok is True
    assert SchemaCheckResult(("meta.instruments",), (), ()).ok is False
    assert SchemaCheckResult((), ("market.index_bar_1m",), ()).ok is False
    assert SchemaCheckResult((), (), ("00_extensions.sql",)).ok is False
    assert SchemaCheckResult((), (), (), ("market.v_etf_nav",)).ok is False
