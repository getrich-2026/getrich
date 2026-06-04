from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

from getrich_data_import.quality.rules import validate_bars


def _valid_bar_columns(rows: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    for column in ["open", "high", "low", "volume", "amount"]:
        if column not in frame.columns:
            frame[column] = frame["close"] if column in {"open", "high", "low"} else 0
    return frame


def test_price_jump_rule_is_disabled_by_default() -> None:
    frame = _valid_bar_columns(
        [
            {"instrument_id": 1, "dt": pd.Timestamp("2026-05-01"), "close": 100},
            {"instrument_id": 1, "dt": pd.Timestamp("2026-05-02"), "close": 150},
        ]
    )

    issues = validate_bars(frame, freq="1d")

    assert [issue.rule for issue in issues] == []


def test_null_price_is_an_error() -> None:
    frame = _valid_bar_columns(
        [
            {"instrument_id": 1, "dt": pd.Timestamp("2026-05-01"), "open": 100, "high": None, "low": 99, "close": 100},
        ]
    )

    issues = validate_bars(frame, freq="1d")

    null_price = [issue for issue in issues if issue.rule == "null_price"]
    assert len(null_price) == 1
    assert null_price[0].severity == "error"
    assert null_price[0].detail["rows"] == 1


def test_price_jump_warns_after_sorting_within_instrument() -> None:
    frame = _valid_bar_columns(
        [
            {"instrument_id": 1, "dt": pd.Timestamp("2026-05-03 09:31"), "close": 131},
            {"instrument_id": 2, "dt": pd.Timestamp("2026-05-01 09:31"), "close": 10},
            {"instrument_id": 1, "dt": pd.Timestamp("2026-05-01 09:31"), "close": 100},
            {"instrument_id": 2, "dt": pd.Timestamp("2026-05-02 09:31"), "close": 11},
            {"instrument_id": 1, "dt": pd.Timestamp("2026-05-02 09:31"), "close": 130},
        ]
    )

    issues = validate_bars(frame, freq="1m", price_jump_warn_pct=0.2)

    price_jump = [issue for issue in issues if issue.rule == "price_jump"]
    assert len(price_jump) == 1
    assert price_jump[0].severity == "warn"
    assert price_jump[0].detail["rows"] == 1
    assert price_jump[0].detail["order_column"] == "dt"
    assert price_jump[0].detail["samples"][0]["instrument_id"] == 1
    assert price_jump[0].detail["samples"][0]["close"] == 130
    json.dumps(price_jump[0].detail)


def test_duplicate_bar_key_is_an_error() -> None:
    frame = _valid_bar_columns(
        [
            {"instrument_id": 1, "dt": pd.Timestamp("2026-05-01 09:31"), "trading_day": date(2026, 5, 1), "close": 10},
            {"instrument_id": 1, "dt": pd.Timestamp("2026-05-01 09:31"), "trading_day": date(2026, 5, 1), "close": 10},
        ]
    )

    issues = validate_bars(frame, freq="1m")

    duplicate = [issue for issue in issues if issue.rule == "duplicate_bar_key"]
    assert len(duplicate) == 1
    assert duplicate[0].severity == "error"
    assert duplicate[0].detail["rows"] == 2


def test_expected_minutes_warns_for_missing_and_extra_counts() -> None:
    frame = _valid_bar_columns(
        [
            {"instrument_id": 1, "dt": pd.Timestamp("2026-05-01 09:31"), "trading_day": date(2026, 5, 1), "close": 10},
            {"instrument_id": 2, "dt": pd.Timestamp("2026-05-01 09:31"), "trading_day": date(2026, 5, 1), "close": 10},
            {"instrument_id": 2, "dt": pd.Timestamp("2026-05-01 09:32"), "trading_day": date(2026, 5, 1), "close": 10},
            {"instrument_id": 2, "dt": pd.Timestamp("2026-05-01 09:33"), "trading_day": date(2026, 5, 1), "close": 10},
        ]
    )

    issues = validate_bars(frame, freq="1m", expected_minutes_per_day=2)

    assert [issue.rule for issue in issues if "minute" in issue.rule] == [
        "missing_minute_bars",
        "extra_minute_bars",
    ]
    assert issues[[issue.rule for issue in issues].index("missing_minute_bars")].detail["rows"] == 1
    assert issues[[issue.rule for issue in issues].index("extra_minute_bars")].detail["rows"] == 1


def test_missing_trading_days_warns_when_expected_calendar_is_supplied() -> None:
    frame = _valid_bar_columns(
        [
            {"instrument_id": "A", "trading_day": date(2026, 5, 1), "close": 10},
            {"instrument_id": "B", "trading_day": date(2026, 5, 1), "close": 10},
            {"instrument_id": "B", "trading_day": date(2026, 5, 2), "close": 11},
        ]
    )

    issues = validate_bars(
        frame,
        freq="1d",
        expected_trading_days=[date(2026, 5, 1), date(2026, 5, 2)],
    )

    missing = [issue for issue in issues if issue.rule == "missing_trading_day_bars"]
    assert len(missing) == 1
    assert missing[0].severity == "warn"
    assert missing[0].detail["missing_count"] == 1
    assert missing[0].detail["samples"][0]["instrument_id"] == "A"


def test_expected_minutes_rejects_non_positive_value() -> None:
    frame = _valid_bar_columns(
        [
            {"instrument_id": 1, "dt": pd.Timestamp("2026-05-01 09:31"), "trading_day": date(2026, 5, 1), "close": 10},
        ]
    )

    with pytest.raises(ValueError, match="positive"):
        validate_bars(frame, freq="1m", expected_minutes_per_day=0)


def test_price_jump_can_sort_by_trading_day() -> None:
    frame = _valid_bar_columns(
        [
            {"instrument_id": 1, "trading_day": date(2026, 5, 2), "close": 80},
            {"instrument_id": 1, "trading_day": date(2026, 5, 1), "close": 100},
        ]
    )

    issues = validate_bars(frame, freq="1d", price_jump_warn_pct=0.19)

    assert [issue.rule for issue in issues] == ["price_jump"]
    assert issues[0].detail["order_column"] == "trading_day"


def test_price_jump_rejects_negative_threshold() -> None:
    frame = _valid_bar_columns(
        [
            {"instrument_id": 1, "dt": pd.Timestamp("2026-05-01"), "close": 100},
            {"instrument_id": 1, "dt": pd.Timestamp("2026-05-02"), "close": 101},
        ]
    )

    with pytest.raises(ValueError, match="non-negative"):
        validate_bars(frame, freq="1d", price_jump_warn_pct=-0.1)
