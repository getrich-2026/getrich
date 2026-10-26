"""数量、字节数与时长格式化的正常值及边界回归。"""

from __future__ import annotations

import pytest
from gr_tools import human


@pytest.mark.parametrize(
    ("value", "decimal", "auto_scale", "expected"),
    [
        (0, 0, False, "0 rows"),
        (1, 0, False, "1 row"),
        (-1, 0, False, "-1 row"),
        (10, 0, False, "10 rows"),
        (1.1, 0, False, "1 row"),
        (-1.1, 0, False, "-1 row"),
        (-0.01, 0, False, "0 rows"),
        (1.5, 1, False, "1.5 rows"),
        (1.5, 3, False, "1.5 rows"),
        (2**53 + 1, 0, False, "9007199254740993 rows"),
        (1000, 0, True, "1K rows"),
        (1500, 0, True, "1.5K rows"),
        (999.9, 0, True, "1K rows"),
        (999.9, 1, True, "999.9 rows"),
        (999999, 0, True, "1M rows"),
        (-999999, 0, True, "-1M rows"),
        (10**15, 0, True, "1000T rows"),
    ],
)
def test_unit_formats_and_promotes_rounded_values(
    value: int | float, decimal: int, auto_scale: bool, expected: str
) -> None:
    assert human.unit(value, "row", decimal=decimal, auto_scale=auto_scale) == expected


def test_unit_does_not_duplicate_plural_suffix() -> None:
    assert human.unit(2, "rows") == "2 rows"


@pytest.mark.parametrize(
    ("value", "decimal", "expected"),
    [
        (0, 1, "0 B"),
        (512, 1, "512 B"),
        (1023.9, 1, "1023 B"),
        (1024, 1, "1 KB"),
        (1536, 1, "1.5 KB"),
        (-1536, 1, "-1.5 KB"),
        (1536, 0, "2 KB"),
        (1536, 2, "1.5 KB"),
        (1024**2 - 1, 1, "1 MB"),
        (-(1024**2 - 1), 1, "-1 MB"),
        (1024**3 - 1, 1, "1 GB"),
        (1024**6, 1, "1 EB"),
        (1024**7, 1, "1024 EB"),
    ],
)
def test_bytes_size_formats_and_promotes_rounded_values(
    value: int | float, decimal: int, expected: str
) -> None:
    assert human.bytes_size(value, decimal=decimal) == expected


@pytest.mark.parametrize("value", [1, 1024])
def test_quantity_formatters_reject_negative_precision(value: int) -> None:
    with pytest.raises(ValueError, match="decimal places"):
        human.unit(value, "row", decimal=-1)
    with pytest.raises(ValueError, match="decimal places"):
        human.bytes_size(value, decimal=-1)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), 10**400])
def test_formatters_reject_non_finite_or_unrepresentable_values(value: int | float) -> None:
    with pytest.raises(ValueError, match="finite"):
        human.unit(value, "row")
    with pytest.raises(ValueError, match="finite"):
        human.bytes_size(value)
    with pytest.raises(ValueError, match="finite"):
        human.sec2str(value)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0µs"),
        (-0.0, "0µs"),
        (0.0005, "500µs"),
        (-1e-9, "0µs"),
        (0.0009996, "1ms"),
        (0.001, "1ms"),
        (0.5, "500ms"),
        (0.9996, "1.00s"),
        (1.5, "1.50s"),
        (10, "10.0s"),
        (9.996, "10.0s"),
        (59.94, "59.9s"),
        (59.97, "1 min"),
        (-59.97, "-1 min"),
        (60, "1 min"),
        (150, "2 mins 30s"),
        (-1.5, "-1.50s"),
        (-150, "-2 mins 30s"),
        (3600, "1 hr"),
        (3901, "1 hr 5 mins"),
        (86400, "1 day"),
        (90000, "1 day 1 hr"),
        (86400 * 10**12, "1000000000000 days"),
    ],
)
def test_sec2str_preserves_readable_duration_formats(seconds: float, expected: str) -> None:
    assert human.sec2str(seconds) == expected
