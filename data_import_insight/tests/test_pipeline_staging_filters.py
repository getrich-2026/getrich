from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from getrich_data_import.orchestration import pipeline as pipeline_module
from getrich_data_import.orchestration.pipeline import ImportPipeline
from getrich_data_import.orchestration.pipeline import _filter_frame_by_date_range
from getrich_data_import.services import TradingCalendarMissingError


def test_filter_frame_by_date_range_prefers_begin_date_for_interval_data() -> None:
    frame = pd.DataFrame(
        [
            {
                "htsc_code": "000001.SZ",
                "begin_date": pd.Timestamp("2025-06-12"),
                "end_date": pd.Timestamp("2025-10-14"),
            },
            {
                "htsc_code": "000001.SZ",
                "begin_date": pd.Timestamp("2025-10-15"),
                "end_date": pd.Timestamp("2026-06-11"),
            },
        ]
    )

    out = _filter_frame_by_date_range(
        frame,
        start_date=date(2020, 1, 1),
        end_date=date(2026, 6, 4),
    )

    assert out["begin_date"].tolist() == [
        pd.Timestamp("2025-06-12"),
        pd.Timestamp("2025-10-15"),
    ]


def test_assign_minute_trading_days_keeps_staged_day_when_calendar_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _MissingCalendar:
        def __init__(self, _conn: object) -> None:
            pass

        def assign_trading_day(self, *_args: object) -> date:
            raise TradingCalendarMissingError("missing calendar")

    class _Source:
        provider = "insight"
        name = "insight"

    monkeypatch.setattr(pipeline_module, "TradingCalendarService", _MissingCalendar)
    pipeline = ImportPipeline(
        settings=SimpleNamespace(),
        engine=None,  # type: ignore[arg-type]
        source=_Source(),  # type: ignore[arg-type]
    )
    frame = pd.DataFrame(
        [
            {
                "exchange": "XSGE",
                "dt": pd.Timestamp("2026-06-04 09:01:00", tz="Asia/Shanghai"),
                "trading_day": date(2026, 6, 4),
            }
        ]
    )

    out = pipeline._assign_minute_trading_days(object(), frame)  # type: ignore[arg-type]

    assert out["trading_day"].tolist() == [date(2026, 6, 4)]
