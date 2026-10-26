"""原油 TAS 价差校验的边界回归；不调用供应商或数据库。"""

from __future__ import annotations

import pandas as pd
import pytest
from gr_data.raw.tushare.quote_rules import tas_spread_mask, validate_future_quote_values


def _raw(code: object = "SCTAS2510.INE", **changes: object):
    # 反例会把任意列（含非法数值、非字符串）覆盖进源行，参数不限定为 str。
    row = {
        "ts_code": code,
        "trade_date": "20250903",
        "open": 0.1,
        "high": 0.1,
        "low": -0.1,
        "close": -0.1,
        "pre_close": None,
        "settle": 491.8,
        "pre_settle": 489.8,
        "vol": 2.0,
        "amount": 196.72,
        "oi": None,
    }
    row.update(changes)
    return pd.DataFrame([row])


def _reference(code="SCTAS2510.INE", **changes):
    return pd.DataFrame([{"ts_code": code, "exchange": "INE", "fut_code": "SCTAS", **changes}])


@pytest.mark.parametrize("code", ["SCTAS2510.INE", "SCTASL.INE", "SCTAS.INE"])
def test_signed_tas_quote_kept_unchanged(code):
    raw = _raw(code)
    before = raw.copy(deep=True)
    assert validate_future_quote_values(raw, _reference(code)) == {
        "tas_rows": 1,
        "tas_negative_quote_rows": 1,
    }
    pd.testing.assert_frame_equal(raw, before)
    assert pd.isna(raw.oi.iloc[0]) and raw.close.iloc[0] == -0.1


@pytest.mark.parametrize("value", [-2.0, 0.0, 2.0])
def test_tas_range_boundaries(value):
    assert validate_future_quote_values(_raw(close=value), _reference())["tas_rows"] == 1


@pytest.mark.parametrize("value", [-2.01, 2.01])
def test_tas_out_of_range_rejected(value):
    with pytest.raises(ValueError, match="out of range"):
        validate_future_quote_values(_raw(close=value), _reference())


@pytest.mark.parametrize("column", ["open", "high", "low", "close", "pre_close"])
def test_ordinary_negative_price_still_rejected(column):
    raw = _raw("SC2510.INE", open=487.7, high=496.0, low=486.4, close=493.2, pre_close=490.4)
    raw[column] = -0.1
    with pytest.raises(ValueError, match="Negative ordinary"):
        validate_future_quote_values(raw, _reference("SC2510.INE", fut_code="SC"))


@pytest.mark.parametrize("column", ["settle", "pre_settle", "vol", "amount", "oi"])
def test_tas_nonoffset_values_stay_nonnegative(column):
    with pytest.raises(ValueError, match="Negative future"):
        validate_future_quote_values(_raw(**{column: -1}), _reference())


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), "bad"])
@pytest.mark.parametrize("column", ["low", "settle", "amount", "oi"])
def test_nonfinite_and_nonnumeric_still_rejected(column, value):
    with pytest.raises(ValueError, match="Nonfinite or nonnumeric"):
        validate_future_quote_values(_raw(**{column: value}), _reference())


@pytest.mark.parametrize("column", ["vol", "oi"])
def test_fractional_contract_counts_rejected(column):
    with pytest.raises(ValueError, match="Noninteger"):
        validate_future_quote_values(_raw(**{column: 0.5}), _reference())


@pytest.mark.parametrize("changes", [{"exchange": "SHFE"}, {"fut_code": "SC"}])
def test_tas_requires_reference_confirmation(changes):
    with pytest.raises(ValueError, match="Unverified"):
        validate_future_quote_values(_raw(), _reference(**changes))


def test_unknown_tas_code_is_rejected():
    with pytest.raises(ValueError, match="Unverified"):
        validate_future_quote_values(_raw("SCTAS2511.INE"), _reference())


def test_other_exchange_cannot_get_signed_exception():
    with pytest.raises(ValueError, match="Negative ordinary"):
        validate_future_quote_values(_raw("SCTAS2510.SHF"), _reference())


def test_duplicate_reference_is_rejected():
    with pytest.raises(ValueError, match="Ambiguous"):
        validate_future_quote_values(_raw(), pd.concat([_reference(), _reference()]))


def test_pre_rule_change_requires_zero_offset():
    with pytest.raises(ValueError, match="out of range"):
        validate_future_quote_values(_raw(trade_date="20230410"), _reference())
    assert validate_future_quote_values(_raw(trade_date="20230411"), _reference())["tas_rows"] == 1


def test_null_prices_and_activity_are_preserved():
    raw = _raw(open=None, high=None, low=None, close=None, vol=None, amount=None)
    assert validate_future_quote_values(raw, _reference())["tas_negative_quote_rows"] == 0


def test_previous_tas_close_is_also_a_signed_offset():
    raw = _raw(close=0.0, low=0.0, pre_close=-0.1)
    before = raw.copy(deep=True)
    assert validate_future_quote_values(raw, _reference())["tas_negative_quote_rows"] == 1
    pd.testing.assert_frame_equal(raw, before)


def test_missing_required_column_is_rejected():
    with pytest.raises(ValueError, match="Missing future quote fields"):
        validate_future_quote_values(_raw().drop(columns="settle"), _reference())


def test_empty_frame_returns_zero_counts():
    assert validate_future_quote_values(_raw().iloc[:0], _reference()) == {
        "tas_rows": 0,
        "tas_negative_quote_rows": 0,
    }
    assert tas_spread_mask(_raw().iloc[:0], _reference()).empty
