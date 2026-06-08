"""Tests for the strategy service coercion helpers.

`services/strategy.py` is 879 lines with 10 async service functions
(list_strategies, get_strategy_detail, assert_strategy_owner,
update_strategy, get_equity_curve, get_monthly_returns,
get_backtest_report, list_trades, list_signals_of_strategy,
list_categories) — each has its own dedicated test file
(test_strategy_read, test_strategy_detail, test_strategy_update_xss,
test_strategy_equity_curve, test_strategy_monthly_returns,
test_strategy_list_trades, test_strategy_list_signals_of_strategy,
test_strategy_backtest_report, test_strategy_trades).

The 4 coercion helpers at the bottom of the file
(``_f`` / ``_f_nullable`` / ``_d`` / ``_dt``) are reused by all 10
service functions but are not covered by any of the existing test
files. This module targets them specifically.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from getrich.apps.web.services.strategy import (
    _d,
    _dt,
    _f,
    _f_nullable,
)


# ---------------------------------------------------------------------------
# _f — Decimal / float / None → float (None treated as 0.0)
# ---------------------------------------------------------------------------


class TestF:
    def test_none_returns_zero(self) -> None:
        """None is converted to 0.0 (not None) — protects the frontend
        from NaN propagation."""
        assert _f(None) == 0.0

    def test_decimal_to_float(self) -> None:
        assert _f(Decimal("3.14")) == 3.14

    def test_decimal_integer_value(self) -> None:
        assert _f(Decimal("100")) == 100.0

    def test_int_to_float(self) -> None:
        assert _f(42) == 42.0

    def test_string_to_float(self) -> None:
        assert _f("2.5") == 2.5

    def test_float_passthrough(self) -> None:
        assert _f(1.5) == 1.5

    def test_negative_decimal(self) -> None:
        """Negative PnL values (e.g. ``Decimal("-0.05")``) survive
        unchanged — important for drawdown / loss columns."""
        assert _f(Decimal("-0.05")) == -0.05

    def test_zero_decimal(self) -> None:
        """Edge: 0 is a valid value, not None."""
        assert _f(Decimal("0")) == 0.0
        assert _f(0) == 0.0
        assert _f(0.0) == 0.0


# ---------------------------------------------------------------------------
# _f_nullable — Decimal / float / None → nullable float
# ---------------------------------------------------------------------------


class TestFNullable:
    def test_none_stays_none(self) -> None:
        """None stays None — distinguishes "missing" from "0.0"."""
        assert _f_nullable(None) is None

    def test_decimal_to_float(self) -> None:
        assert _f_nullable(Decimal("1.5")) == 1.5

    def test_int_to_float(self) -> None:
        assert _f_nullable(100) == 100.0

    def test_string_to_float(self) -> None:
        assert _f_nullable("0.5") == 0.5

    def test_zero_stays_zero(self) -> None:
        """Edge: 0 is a real value, not None — only ``None`` triggers the
        nullable path."""
        assert _f_nullable(0) == 0.0
        assert _f_nullable(0.0) == 0.0
        assert _f_nullable(Decimal("0")) == 0.0

    def test_negative_value(self) -> None:
        assert _f_nullable(Decimal("-1.0")) == -1.0


# ---------------------------------------------------------------------------
# _d — date / None → ISO string (empty for None)
# ---------------------------------------------------------------------------


class TestD:
    def test_none_returns_empty_string(self) -> None:
        """``_d(None)`` returns ``""`` — the column is typed as ``str``,
        so the frontend always gets a string."""
        assert _d(None) == ""

    def test_date_to_isoformat(self) -> None:
        assert _d(date(2026, 1, 1)) == "2026-01-01"

    def test_datetime_to_isoformat(self) -> None:
        """``datetime`` is also acceptable input — isoformat gives the
        full timestamp string."""
        assert _d(datetime(2026, 1, 1, 12, 0, 0)) == "2026-01-01T12:00:00"

    def test_string_passthrough(self) -> None:
        """String inputs are returned as-is (the column is already
        ISO-formatted by the DB driver)."""
        assert _d("2026-01-01") == "2026-01-01"

    def test_datetime_date_subclass(self) -> None:
        """``datetime`` is a subclass of ``date`` — the isinstance check
        catches both. The output is the isoformat of the datetime."""
        d = datetime(2026, 6, 1, 9, 30)
        assert _d(d) == "2026-06-01T09:30:00"


# ---------------------------------------------------------------------------
# _dt — datetime / None → ISO string (empty for None)
# ---------------------------------------------------------------------------


class TestDt:
    def test_none_returns_empty_string(self) -> None:
        """``_dt(None)`` returns ``""`` — the column is typed as ``str``,
        never ``None``."""
        assert _dt(None) == ""

    def test_datetime_to_isoformat(self) -> None:
        assert _dt(datetime(2026, 1, 1, 12, 30, 45)) == "2026-01-01T12:30:45"

    def test_date_to_isoformat(self) -> None:
        """``date`` is also acceptable — converted via str()."""
        assert _dt(date(2026, 1, 1)) == "2026-01-01"

    def test_string_passthrough(self) -> None:
        """String inputs are returned as-is."""
        assert _dt("2026-01-01T00:00:00Z") == "2026-01-01T00:00:00Z"

    def test_datetime_with_microseconds(self) -> None:
        """Microsecond precision is preserved (PG ``timestamp`` has
        microsecond precision; the DB driver returns datetimes with
        microseconds when present)."""
        ts = datetime(2026, 1, 1, 12, 30, 45, 123456)
        assert _dt(ts) == "2026-01-01T12:30:45.123456"


# ---------------------------------------------------------------------------
# Cross-helper invariants
# ---------------------------------------------------------------------------


class TestCrossHelperInvariants:
    """Defensive checks for the contract between helpers."""

    def test_f_and_f_nullable_agree_on_nonnull(self) -> None:
        """For non-None values, ``_f`` and ``_f_nullable`` MUST produce
        the same result — they only differ in the None handling."""
        for v in [Decimal("1.5"), 1, 1.5, "0.5", 0, -0.5]:
            assert _f(v) == _f_nullable(v)

    def test_f_and_f_nullable_disagree_on_none(self) -> None:
        """``_f(None) == 0.0`` while ``_f_nullable(None) is None`` — that
        is the whole point of the split."""
        assert _f(None) == 0.0
        assert _f_nullable(None) is None

    def test_d_and_dt_agree_on_date(self) -> None:
        """A ``date`` passed to either helper produces the same string
        (datetime's isoformat of a date is just the date portion)."""
        d = date(2026, 1, 1)
        assert _d(d) == _dt(d)

    def test_d_and_dt_agree_on_none(self) -> None:
        """Both return ``""`` for None input."""
        assert _d(None) == _dt(None) == ""

    def test_f_does_not_silently_coerce_invalid_string(self) -> None:
        """``float("not-a-number")`` raises — we don't try to be smart.
        This documents the behavior: invalid input bubbles up rather
        than being silently turned into 0.0."""
        with __import__("pytest").raises(ValueError):
            _f("not-a-number")
