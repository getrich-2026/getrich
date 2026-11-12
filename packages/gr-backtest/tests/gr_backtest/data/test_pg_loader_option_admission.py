"""当前期权快照不能通过回测 PG 读取入口冒充历史参数。"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from gr_backtest.data.pg_loader import PgBarLoader
from gr_backtest.exceptions import DataLoadError
from gr_backtest.types import AssetClass


TZ = ZoneInfo("Asia/Shanghai")
START = datetime(2026, 11, 2, tzinfo=TZ)
END = datetime(2026, 11, 7, tzinfo=TZ)
OPTION_CLASSES = [
    "option",
    "OPTION",
    " option",
    "equity_a_option",
    AssetClass.EQUITY_OPTION_A,
    AssetClass.EQUITY_OPTION_A.value,
    AssetClass.COMMODITY_FUTURE_OPTION,
    AssetClass.COMMODITY_FUTURE_OPTION.value,
    AssetClass.INDEX_FUTURE_OPTION,
    AssetClass.INDEX_FUTURE_OPTION.value,
]


@pytest.mark.parametrize("asset_class", OPTION_CLASSES)
@pytest.mark.parametrize("entry", ["bars", "iter_bars", "instruments"])
def test_option_history_refused_before_database_access(asset_class, entry):
    """报价已入库也不能让回测直接消费当前参数或不完整的历史数据。"""
    conn = Mock()
    loader = PgBarLoader(conn)
    with pytest.raises(DataLoadError, match="historical.*parameters"):
        if entry == "bars":
            loader.load_bars(None, START, END, asset_class=asset_class)
        elif entry == "iter_bars":
            list(loader.iter_bars(None, START, END, asset_class=asset_class))
        else:
            loader.load_instruments(asset_class)
    assert not conn.mock_calls


def test_empty_iteration_still_checks_option_admission():
    """空区间不能绕过与普通读取相同的用途门禁。"""
    conn = Mock()
    with pytest.raises(DataLoadError, match="historical.*parameters"):
        list(PgBarLoader(conn).iter_bars(None, START, START, asset_class="option"))
    assert not conn.mock_calls


@pytest.mark.parametrize("entry", ["bars", "iter_bars"])
def test_option_default_subclass_still_requires_historical_parameters(entry):
    class OptionLoader(PgBarLoader):
        DEFAULT_ASSET_CLASS = "option"

    conn = Mock()
    loader = OptionLoader(conn)
    with pytest.raises(DataLoadError, match="historical.*parameters"):
        if entry == "bars":
            loader.load_bars(None, START, END)
        else:
            list(loader.iter_bars(None, START, END))
    assert not conn.mock_calls
