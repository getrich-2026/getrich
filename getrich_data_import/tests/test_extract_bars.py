from __future__ import annotations

from datetime import date

import pytest

from getrich_data_import.extract import BarsExtractionPlan
from getrich_data_import.extract import BarsExtractionRequest


def test_request_normalizes_import_bars_args() -> None:
    request = BarsExtractionRequest.from_import_bars_args(
        asset=" index ",
        freq="1d",
        start_date="2026-05-01",
        end_date=date(2026, 5, 31),
        symbols=[" 000300.XSHG ", "000300.XSHG", "", "IF2406.CCFX"],
        mode="auto",
    )

    assert request.asset == "index"
    assert request.freq == "1d"
    assert request.start_date == date(2026, 5, 1)
    assert request.end_date == date(2026, 5, 31)
    assert request.symbols == ("000300.XSHG", "IF2406.CCFX")
    assert request.table_name == "index_bar_1d"
    assert request.job_name == "import_index_1d"
    assert request.uses_watermark is False


def test_plan_ignores_global_watermark_for_correctness() -> None:
    plan = BarsExtractionPlan.from_import_bars_args(
        asset="future",
        freq="1m",
        start_date="2026-05-01",
        end_date="2026-05-02",
        symbols=["IF2406.CCFX"],
        mode="auto",
    )

    assert plan.table_name == "future_bar_1m"
    assert plan.job_name == "import_future_1m"
    assert plan.uses_watermark is False
    assert plan.source_kwargs(watermark="2026-04-30") == {
        "asset": "future",
        "freq": "1m",
        "since": None,
        "start_date": date(2026, 5, 1),
        "end_date": date(2026, 5, 2),
        "symbols": ["IF2406.CCFX"],
    }


def test_full_mode_ignores_watermark_and_uses_none_for_unfiltered_symbols() -> None:
    plan = BarsExtractionPlan.from_import_bars_args(asset="option", freq="1d", mode="full")

    assert plan.uses_watermark is False
    assert plan.source_kwargs(watermark="2026-04-30") == {
        "asset": "option",
        "freq": "1d",
        "since": None,
        "start_date": None,
        "end_date": None,
        "symbols": None,
    }


@pytest.mark.parametrize(
    ("asset", "freq", "table"),
    [
        ("stock", "1d", "stock_bar_1d"),
        ("stock", "1m", "stock_bar_1m"),
        ("etf", "1d", "etf_bar_1d"),
        ("etf", "1m", "etf_bar_1m"),
    ],
)
def test_plan_supports_stock_and_etf(asset: str, freq: str, table: str) -> None:
    plan = BarsExtractionPlan.from_import_bars_args(asset=asset, freq=freq, mode="full")

    assert plan.table_name == table
    assert plan.job_name == f"import_{asset}_{freq}"


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"asset": "bond", "freq": "1d"}, "unsupported asset"),
        ({"asset": "index", "freq": "5m"}, "unsupported freq"),
        ({"asset": "index", "freq": "1d", "mode": "incremental"}, "unsupported mode"),
        (
            {"asset": "index", "freq": "1d", "start_date": "2026-06-01", "end_date": "2026-05-01"},
            "start_date 2026-06-01 is after end_date 2026-05-01",
        ),
        ({"asset": "index", "freq": "1d", "start_date": "20260501"}, "YYYY-MM-DD"),
    ],
)
def test_request_rejects_invalid_args(kwargs: dict[str, object], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        BarsExtractionRequest.from_import_bars_args(**kwargs)
