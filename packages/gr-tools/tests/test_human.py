"""``gr_tools.human`` 的行为测试。"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from gr_tools import human


def test_unit_pluralizes_and_scales() -> None:
    assert human.unit(1, "apple") == "1 apple"
    assert human.unit(10, "apple") == "10 apples"
    assert human.unit(1500, "user", auto_scale=True) == "1.5K users"


def test_unit_rejects_negative_decimal() -> None:
    with pytest.raises(ValueError, match="decimal places"):
        human.unit(1, "apple", decimal=-1)


def test_bytes_size() -> None:
    assert human.bytes_size(512) == "512 B"
    assert human.bytes_size(1536) == "1.5 KB"


def test_sec2str() -> None:
    assert human.sec2str(0.0005) == "500µs"
    assert human.sec2str(0.5) == "500ms"
    assert human.sec2str(1.5) == "1.50s"
    assert human.sec2str(150) == "2 mins 30s"
    assert human.sec2str(-1.5) == "-1.50s"


def test_lists_truncates() -> None:
    assert human.lists(None) == "None"
    assert human.lists([]) == "[]"
    assert human.lists([1, 2]) == "[1, 2]"
    assert human.lists([1, 2, 3, 4, 5]) == "[1, 2, 3] (& 2 others)"


def test_ranges_accepts_mixed_date_types() -> None:
    assert human.ranges([]) == "No dates"
    assert human.ranges([date(2026, 8, 11)]) == "2026-08-11 (1 day)"
    assert human.ranges(["2026-08-14", 20260811, datetime(2026, 8, 12)]) == (
        "2026-08-11 ~ 2026-08-14 (3 days, 4D)"
    )


def test_ranges_invalid_input_does_not_raise() -> None:
    assert human.ranges(["not-a-date"]) == "1 items (invalid dates)"


def test_datetime_str_shortcuts_and_fallback() -> None:
    assert human.datetime_str("2026-08-11") == "2026-08-11"
    assert human.datetime_str(20260811, "compact") == "20260811"
    assert human.datetime_str(date(2026, 8, 11), "%m/%d") == "08/11"
    assert human.datetime_str("garbage") == "garbage"


def test_track_yields_every_item() -> None:
    collected = list(human.track([1, 2, 3], msg="test", reporter=lambda _: None))
    assert collected == [1, 2, 3]
    assert list(human.track(3, reporter=lambda _: None)) == [0, 1, 2]
