from __future__ import annotations

import pandas as pd

from getrich_data_import.adapters.yinhe_parquet import YinheParquetSource


def test_factor_series_lazily_reads_one_symbol_and_caches(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    factor_dir = data_dir / "backward_factor"
    factor_dir.mkdir(parents=True)
    factor_path = factor_dir / "factors.parquet"
    pd.DataFrame(
        {"600000.SH": [1.0, 1.1], "600004.SH": [1.0, 0.9]},
        index=pd.to_datetime(["2026-05-01", "2026-05-02"]),
    ).to_parquet(factor_path)

    original_read_parquet = pd.read_parquet
    calls: list[dict[str, object]] = []

    def tracking_read_parquet(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return original_read_parquet(*args, **kwargs)

    monkeypatch.setattr(pd, "read_parquet", tracking_read_parquet)
    source = YinheParquetSource(data_dir)

    first = source.factor_series("600000.SH")
    second = source.factor_series("600000.SH")

    assert first is second
    assert first is not None
    assert first.tolist() == [1.0, 1.1]
    assert calls == [{"args": (factor_path,), "kwargs": {"columns": ["600000.SH"]}}]


def test_kline_paths_are_limited_to_requested_symbols(tmp_path) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "kline_day" / "600000.SH").mkdir(parents=True)
    (data_dir / "kline_day" / "600004.SH").mkdir(parents=True)
    wanted = data_dir / "kline_day" / "600000.SH" / "2026-05.parquet"
    other = data_dir / "kline_day" / "600004.SH" / "2026-05.parquet"
    wanted.write_bytes(b"")
    other.write_bytes(b"")
    source = YinheParquetSource(data_dir)

    assert source._kline_paths("1d", symbols={"600000.SH"}) == [wanted]


def test_calendar_frames_copy_single_a_share_calendar_to_missing_exchange(tmp_path) -> None:
    data_dir = tmp_path / "data"
    calendar_dir = data_dir / "calendar"
    calendar_dir.mkdir(parents=True)
    pd.DataFrame(index=[20260601, 20260602]).to_parquet(calendar_dir / "calendar_SH.parquet")
    source = YinheParquetSource(data_dir)

    frames = list(source.calendar_frames())

    assert [frame["exchange"].iloc[0] for frame in frames] == ["SH", "SZ"]
    assert [frame["trading_day"].tolist() for frame in frames] == [
        frames[0]["trading_day"].tolist(),
        frames[0]["trading_day"].tolist(),
    ]


def test_calendar_frames_do_not_copy_a_share_calendar_when_alias_exists(tmp_path) -> None:
    data_dir = tmp_path / "data"
    calendar_dir = data_dir / "calendar"
    calendar_dir.mkdir(parents=True)
    pd.DataFrame(index=[20260601]).to_parquet(calendar_dir / "calendar_SH.parquet")
    pd.DataFrame(index=[20260602]).to_parquet(calendar_dir / "calendar_SZ.parquet")
    source = YinheParquetSource(data_dir)

    frames = list(source.calendar_frames())

    assert [frame["exchange"].iloc[0] for frame in frames] == ["SH", "SZ"]
    assert frames[0]["trading_day"].tolist() != frames[1]["trading_day"].tolist()


def test_future_contract_frame_uses_hist_code_list_fields(tmp_path) -> None:
    data_dir = tmp_path / "data"
    hist_dir = data_dir / "hist_code_list"
    hist_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "symbol": "IF2406.CFFEX",
                "underlying": "IF",
                "multiplier": "300",
                "price_tick": "0.2",
                "list_date": "2024-01-01",
                "last_trade_date": "2024-06-21",
            }
        ]
    ).to_parquet(hist_dir / "hist_code_list_EXTRA_FUTURE_CFFEX.parquet")
    source = YinheParquetSource(data_dir)

    frame = source.future_contract_frame()

    assert frame.loc[0, "asset"] == "future"
    assert frame.loc[0, "exchange"] == "CFFEX"
    assert frame.loc[0, "underlying"] == "IF"
    assert frame.loc[0, "multiplier"] == 300
