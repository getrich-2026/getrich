from __future__ import annotations

from getrich_data_import.db.migrations import _checksum


def test_checksum_is_stable() -> None:
    assert _checksum("select 1;") == _checksum("select 1;")
    assert _checksum("select 1;") != _checksum("select 2;")

