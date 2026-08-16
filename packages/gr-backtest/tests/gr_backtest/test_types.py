"""Tests for the Frequency enum and related types."""

from __future__ import annotations

from gr_backtest.types import Frequency


class TestFrequency:
    def test_all_values_contains_all_entries(self) -> None:
        values = Frequency.all_values()
        assert values == frozenset({"1m", "5m", "15m", "30m", "60m", "1h", "1d"})

    def test_is_valid_accepts_known(self) -> None:
        for freq in ("1m", "5m", "15m", "30m", "60m", "1h", "1d"):
            assert Frequency.is_valid(freq), f"expected {freq!r} to be valid"

    def test_is_valid_rejects_unknown(self) -> None:
        assert not Frequency.is_valid("2m")
        assert not Frequency.is_valid("weekly")
        assert not Frequency.is_valid("")
        assert not Frequency.is_valid("1H")  # case-sensitive

    def test_str_equality(self) -> None:
        assert Frequency.FIVE_MIN == "5m"
        assert Frequency.ONE_HOUR == "1h"
        assert Frequency.SIXTY_MIN == "60m"
        assert Frequency.ONE_DAY == "1d"

    def test_one_hour_is_valid(self) -> None:
        assert Frequency.is_valid("1h")

    def test_sixty_min_is_valid(self) -> None:
        assert Frequency.is_valid("60m")

    def test_backward_compat_one_min_value(self) -> None:
        assert Frequency.ONE_MIN.value == "1m"

    def test_backward_compat_one_day_value(self) -> None:
        assert Frequency.ONE_DAY.value == "1d"

    def test_one_hour_and_sixty_min_are_different_members(self) -> None:
        # Same semantic frequency, but different string values
        assert Frequency.ONE_HOUR is not Frequency.SIXTY_MIN
        assert Frequency.ONE_HOUR.value == "1h"
        assert Frequency.SIXTY_MIN.value == "60m"
