from datetime import date, datetime
from unittest.mock import MagicMock

from import_data.realtime.insight_handler import InsightBarHandler, normalize_insight_symbol


def test_symbol_normalization():
    assert normalize_insight_symbol("600000.SH") == "600000.SH"
    assert normalize_insight_symbol("IF2503.CF") == "IF2503.CFE"
    assert normalize_insight_symbol("RB2505.SHF") == "RB2505.SHF"
    assert normalize_insight_symbol("M2505.ZCE") == "M2505.CZC"
    assert normalize_insight_symbol("600000") == "600000"  # 无后缀，原样返回


def test_on_bar_calls_bridge():
    mock_bridge = MagicMock()
    handler = InsightBarHandler(mock_bridge)

    bar = MagicMock()
    bar.htsc_code = "600000.SH"
    bar.time = datetime(2026, 5, 26, 10, 1, 0)
    bar.pre_close = 10.0
    bar.open = 10.1
    bar.high = 10.2
    bar.low = 10.0
    bar.close = 10.15
    bar.volume = 1000.0
    bar.value = 10150.0
    bar.open_interest = 0.0
    bar.settle = 0.0
    bar.pre_settle = 0.0

    handler.on_bar(bar)

    mock_bridge.put_nowait_threadsafe.assert_called_once()
    event = mock_bridge.put_nowait_threadsafe.call_args[0][0]
    assert event.symbol == "600000.SH"
    assert event.close == 10.15
    assert event.provider == "insight"
    assert event.dt == date(2026, 5, 26)


def test_on_bar_error_does_not_raise():
    """on_bar 内部错误不应向外传播（不能阻塞 SDK 线程）。"""
    mock_bridge = MagicMock()
    handler = InsightBarHandler(mock_bridge)

    bad_bar = object()  # 没有任何属性，_convert 会出错
    handler.on_bar(bad_bar)  # 不应 raise
