from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from getrich_data_import.adapters.ricequant import RiceQuantSource
from getrich_data_import.common.config import RicequantSettings


def test_ricequant_init_with_tcp_license_env_file(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("RQDATAC_LICENSE=test-license\n", encoding="utf-8")
    monkeypatch.delenv("RQDATAC_LICENSE", raising=False)

    settings = RicequantSettings(env_file=env_file, login_required=True)
    source = RiceQuantSource(settings)

    mock_rq = MagicMock()
    with patch.dict("sys.modules", {"rqdatac": mock_rq}):
        source._init_api()

    mock_rq.init.assert_called_once_with(
        "tcp://license:test-license@rqdatad-pro.ricequant.com:16011"
    )


def test_ricequant_convert_symbols_uses_id_convert() -> None:
    settings = RicequantSettings(login_required=False)
    source = RiceQuantSource(settings)
    source._initialized = True

    mock_rq = MagicMock()
    mock_rq.id_convert.return_value = ["000001.XSHE"]
    with patch.dict("sys.modules", {"rqdatac": mock_rq}):
        converted = source.convert_symbols(["000001.SZ"])

    assert converted == ["000001.XSHE"]
    mock_rq.id_convert.assert_called_once_with(["000001.SZ"], to=None)


def test_ricequant_calendar_passes_market() -> None:
    settings = RicequantSettings(
        default_start_date=date(2026, 1, 1),
        default_end_date=date(2026, 1, 2),
        market="hk",
        login_required=False,
    )
    source = RiceQuantSource(settings)
    source._initialized = True

    mock_rq = MagicMock()
    mock_rq.get_trading_dates.return_value = [date(2026, 1, 1)]
    with patch.dict("sys.modules", {"rqdatac": mock_rq}):
        frames = list(source.calendar_frames())

    assert frames
    mock_rq.get_trading_dates.assert_called_once_with(
        date(2026, 1, 1), date(2026, 1, 2), market="hk"
    )


def test_ricequant_timezone_crash_fix() -> None:
    settings = RicequantSettings(default_start_date=date(2026, 1, 1), default_end_date=date(2026, 1, 2), login_required=False)
    source = RiceQuantSource(settings)
    source._initialized = True

    mock_rq = MagicMock()
    with patch.dict("sys.modules", {"rqdatac": mock_rq}):
        raw_df = pd.DataFrame({
            "order_book_id": ["000001.XSHE"],
            "datetime": [pd.Timestamp("2026-01-01 09:31:00", tz="Asia/Shanghai")],
            "open": [10.0],
            "close": [10.1]
        })
        mock_rq.get_price.return_value = raw_df

        frames = list(source.bar_frames(asset="stock", freq="1m", symbols=["000001.XSHE"]))

        assert len(frames) == 1
        df = frames[0]
        assert str(df["dt"].iloc[0].tz) == "Asia/Shanghai"
        assert len(df) == 1


def test_ricequant_source_symbol_silent_pollution_multi(caplog: pytest.LogCaptureFixture) -> None:
    """多标的缺少 order_book_id：应 continue + 记录 warning，不产生任何输出帧。"""
    settings = RicequantSettings(default_start_date=date(2026, 1, 1), default_end_date=date(2026, 1, 2), login_required=False)
    source = RiceQuantSource(settings)
    source._initialized = True

    mock_rq = MagicMock()
    with patch.dict("sys.modules", {"rqdatac": mock_rq}):
        # 模拟多标的请求但缺 order_book_id 列
        raw_df = pd.DataFrame({
            "datetime": [pd.Timestamp("2026-01-01 09:31:00")],
            "open": [10.0],
            "close": [10.1]
        })
        mock_rq.get_price.return_value = raw_df

        import logging
        with caplog.at_level(logging.WARNING, logger="getrich_data_import.adapters.ricequant"):
            frames = list(source.bar_frames(asset="stock", freq="1m", symbols=["000001.XSHE", "600000.XSHG"]))

        assert len(frames) == 0
        # 验证 warning 被记录
        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("order_book_id" in str(msg) for msg in warning_messages), (
            f"期望 warning 含 'order_book_id'，实际记录：{warning_messages}"
        )


def test_ricequant_single_symbol_no_order_book_id_column() -> None:
    """单标的请求不返回 order_book_id 列时，数据不应被丢弃，source_symbol 应正确回填。

    rqdatac 对单个 symbol 的 get_price 请求使用 DatetimeIndex，
    reset_index 后不含 order_book_id 列，此时应安全回填 chunk[0]。
    """
    settings = RicequantSettings(default_start_date=date(2026, 1, 1), default_end_date=date(2026, 1, 2), login_required=False)
    source = RiceQuantSource(settings)
    source._initialized = True

    mock_rq = MagicMock()
    with patch.dict("sys.modules", {"rqdatac": mock_rq}):
        # 模拟单标的：无 order_book_id 列
        raw_df = pd.DataFrame({
            "datetime": [pd.Timestamp("2026-01-01 09:31:00", tz="Asia/Shanghai")],
            "open": [10.0],
            "high": [10.5],
            "low": [9.9],
            "close": [10.1],
            "volume": [1000.0],
        })
        mock_rq.get_price.return_value = raw_df

        frames = list(source.bar_frames(asset="stock", freq="1m", symbols=["000001.XSHE"]))

        # 数据不应被丢弃
        assert len(frames) == 1, f"期望 1 帧，实际 {len(frames)} 帧（单标的数据被静默丢弃）"
        df = frames[0]
        assert len(df) == 1
        # source_symbol 必须正确回填为请求的 symbol
        assert df["source_symbol"].iloc[0] == "000001.XSHE", (
            f"source_symbol 应为 '000001.XSHE'，实际为 '{df['source_symbol'].iloc[0]}'"
        )


def test_ricequant_bar_frames_passes_market() -> None:
    settings = RicequantSettings(
        default_start_date=date(2026, 1, 1),
        default_end_date=date(2026, 1, 2),
        market="hk",
        login_required=False,
    )
    source = RiceQuantSource(settings)
    source._initialized = True

    mock_rq = MagicMock()
    with patch.dict("sys.modules", {"rqdatac": mock_rq}):
        raw_df = pd.DataFrame({
            "order_book_id": ["000001.XSHE"],
            "date": [pd.Timestamp("2026-01-01")],
            "open": [10.0],
            "close": [10.1],
        })
        mock_rq.get_price.return_value = raw_df

        frames = list(source.bar_frames(asset="stock", freq="1d", symbols=["000001.XSHE"]))

    assert len(frames) == 1
    _, kwargs = mock_rq.get_price.call_args
    assert kwargs["market"] == "hk"


def test_ricequant_night_session_trading_day() -> None:
    settings = RicequantSettings(default_start_date=date(2026, 1, 1), default_end_date=date(2026, 1, 2), login_required=False)
    source = RiceQuantSource(settings)
    source._initialized = True

    mock_rq = MagicMock()
    with patch.dict("sys.modules", {"rqdatac": mock_rq}):
        raw_df = pd.DataFrame({
            "order_book_id": ["IF2406"],
            "datetime": [pd.Timestamp("2026-01-01 21:01:00")],
            "trading_date": [pd.Timestamp("2026-01-02").date()],
            "open": [10.0],
            "close": [10.1]
        })
        mock_rq.get_price.return_value = raw_df

        frames = list(source.bar_frames(asset="future", freq="1m", symbols=["IF2406"]))

        assert len(frames) == 1
        df = frames[0]
        assert df["trading_day"].iloc[0] == date(2026, 1, 2)
        assert df["dt"].iloc[0].hour == 21


def test_ricequant_trading_period_frames_normalize_schema() -> None:
    settings = RicequantSettings(
        default_start_date=date(2026, 1, 1),
        default_end_date=date(2026, 1, 2),
        market="cn",
        symbols=("000001.XSHE",),
        login_required=False,
    )
    source = RiceQuantSource(settings)
    source._initialized = True

    raw = pd.DataFrame(
        {"trading_hours": ["09:31-11:30,13:01-15:00"]},
        index=pd.MultiIndex.from_tuples(
            [("000001.XSHE", pd.Timestamp("2026-01-01"))],
            names=["order_book_id", "date"],
        ),
    )

    mock_rq = MagicMock()
    mock_rq.get_trading_periods.return_value = raw
    with patch.dict("sys.modules", {"rqdatac": mock_rq}):
        frames = list(source.trading_period_frames(frequency="1m"))

    assert len(frames) == 1
    df = frames[0]
    assert df.to_dict("records") == [
        {
            "source_symbol": "000001.XSHE",
            "trading_day": date(2026, 1, 1),
            "frequency": "1m",
            "trading_hours": "09:31-11:30,13:01-15:00",
            "source": "ricequant",
        }
    ]
    mock_rq.get_trading_periods.assert_called_once_with(
        ["000001.XSHE"],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
        frequency="1m",
        market="cn",
    )
