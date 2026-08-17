"""``gr-picks`` 命令行入口。

CLI 是薄壳，这里只验参数透传与退出码 —— 业务逻辑的用例在
``test_pick_import.py``。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from gr_api import picks_cli
from gr_api.errors import Conflict
from gr_api.services.pick_import import PickImportResult


def _result(**overrides: Any) -> PickImportResult:
    payload: dict[str, Any] = {
        "status": "committed",
        "strategy_id": "uuid-1",
        "strategy_code": "STR_STK_001",
        "trading_day": date(2026, 8, 12),
        "batch_id": 7,
        "summary": {"total_rows": 4, "valid_rows": 4, "error_rows": 0, "will_delete": 0},
        "errors": [],
        "warnings": [],
    }
    payload.update(overrides)
    return PickImportResult(**payload)


def test_cli_passes_arguments_through(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, Any] = {}
    csv_path = tmp_path / "picks.csv"
    csv_path.write_text("symbol\n600000.SH\n", encoding="utf-8")

    def fake_import(**kwargs: Any) -> PickImportResult:
        captured.update(kwargs)
        return _result()

    monkeypatch.setattr(picks_cli, "import_picks_sync", fake_import)

    code = picks_cli.main(
        [
            "import",
            "--strategy",
            "STR_STK_001",
            "--trading-day",
            "2026-08-12",
            "--file",
            str(csv_path),
            "--overwrite",
            "--allow-empty",
            "--note",
            "本期备注",
        ]
    )

    assert code == 0
    assert captured["strategy"] == "STR_STK_001"
    assert captured["trading_day"] == "2026-08-12"
    assert str(captured["source"]) == str(csv_path)
    assert captured["overwrite"] is True
    assert captured["allow_empty"] is True
    assert captured["dry_run"] is False
    assert captured["note"] == "本期备注"
    assert "batch_id=7" in capsys.readouterr().out


def test_cli_returns_nonzero_when_blocked(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    blocked = _result(
        status="blocked",
        batch_id=None,
        summary={"total_rows": 1, "valid_rows": 0, "error_rows": 1},
        errors=[
            {
                "row_number": 2,
                "column": "symbol",
                "error_code": "invalid_symbol",
                "message": "invalid symbol: '600000'",
                "raw_row": {},
            }
        ],
    )
    monkeypatch.setattr(picks_cli, "import_picks_sync", lambda **_: blocked)

    code = picks_cli.main(
        ["import", "--strategy", "S", "--trading-day", "2026-08-12", "--file", "x.csv"]
    )

    assert code == 1
    assert "ERROR row 2" in capsys.readouterr().out


def test_cli_reports_api_errors_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def boom(**_: Any) -> PickImportResult:
        raise Conflict("an active batch already exists for 2026-08-12")

    monkeypatch.setattr(picks_cli, "import_picks_sync", boom)

    code = picks_cli.main(
        ["import", "--strategy", "S", "--trading-day", "2026-08-12", "--file", "x.csv"]
    )

    assert code == 1
    assert "active batch already exists" in capsys.readouterr().err


def test_cli_prints_warnings(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        picks_cli,
        "import_picks_sync",
        lambda **_: _result(warnings=["上一交易日无数据，入池时间按沿用处理（2 条）"]),
    )

    code = picks_cli.main(
        ["import", "--strategy", "S", "--trading-day", "2026-08-12", "--file", "x.csv"]
    )

    assert code == 0
    assert "WARN" in capsys.readouterr().out
