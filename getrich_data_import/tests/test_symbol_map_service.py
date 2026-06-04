from __future__ import annotations

import pytest

from getrich_data_import.services.symbol_map import SymbolMapService


class _Rows:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self):
        return iter(self._rows)


class _Conn:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.params = None

    def execute(self, _sql, params):
        self.params = params
        return _Rows(self.rows)


def test_resolve_many_returns_mapping_by_source_symbol() -> None:
    conn = _Conn(
        [
            {
                "source": "insight",
                "source_symbol": "IF2406.CCFX",
                "instrument_id": 10,
                "symbol": "IF2406.CCFX",
                "asset": "future",
                "exchange": "CCFX",
            }
        ]
    )

    service = SymbolMapService(conn)  # type: ignore[arg-type]
    result = service.resolve_many(source="insight", source_symbols=["IF2406.CCFX"])

    assert result["IF2406.CCFX"].instrument_id == 10
    assert result["IF2406.CCFX"].asset == "future"
    assert conn.params == {"source": "insight", "source_symbols": ["IF2406.CCFX"]}


def test_resolve_many_rejects_missing_symbols() -> None:
    service = SymbolMapService(_Conn([]))  # type: ignore[arg-type]

    with pytest.raises(LookupError, match="symbol_map missing"):
        service.resolve_many(source="yinhe", source_symbols=["000300.SH"])


def test_resolve_one_uses_many() -> None:
    service = SymbolMapService(
        _Conn(
            [
                {
                    "source": "yinhe",
                    "source_symbol": "000300.SH",
                    "instrument_id": 1,
                    "symbol": "000300.SH",
                    "asset": "index",
                    "exchange": "SH",
                }
            ]
        )
    )  # type: ignore[arg-type]

    result = service.resolve_one(source="yinhe", source_symbol="000300.SH")

    assert result.instrument_id == 1

