"""Tushare 归一化逻辑单测（不需要数据库）。

重点覆盖迁移中最容易丢失的语义：单位换算、复权因子必需性、
涨跌停价的一致性校验、停复牌 → trading_status。
"""

from __future__ import annotations

import pandas as pd
import pytest
from gr_data.ingest.tushare.importers.reference import parse_date
from gr_data.ingest.tushare.symbols import split_ts_code
from gr_data.raw.tushare.fetchers.bars import month_range


# --------------------------------------------------------------------------- #
# 代码归一化
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "code,expected",
    [
        ("600000.SH", "XSHG"),
        ("000001.SZ", "XSHE"),
        ("430047.BJ", "XBSE"),
        # Tushare 的期货后缀与通行简称不同，必须显式映射
        ("CU2401.SHF", "SHFE"),
        ("CF401.ZCE", "CZCE"),
        ("IF2401.CFX", "CFFEX"),
        ("SI2401.GFE", "GFEX"),
        ("SC2401.INE", "INE"),
        ("801010.SI", "SW"),
    ],
)
def test_split_ts_code_exchange(code, expected):
    symbol, exchange = split_ts_code(code)
    assert exchange == expected
    # symbol 保留完整带后缀代码，避免跨市场重号
    assert symbol == code


def test_split_ts_code_unknown_suffix_not_rewritten():
    assert split_ts_code("123456.XX") == ("123456.XX", "XX")
    assert split_ts_code("noSuffix") == ("noSuffix", "UNKNOWN")


# --------------------------------------------------------------------------- #
# 日期解析
# --------------------------------------------------------------------------- #
def test_parse_date_ok():
    assert parse_date("20240102") == pd.Timestamp("2024-01-02").date()


@pytest.mark.parametrize("blank", [None, "", "  ", "0", "00000000", float("nan")])
def test_parse_date_blank_to_none(blank):
    assert parse_date(blank) is None


def test_parse_date_invalid_raises():
    """非法日期必须抛错，不能静默变 None——那会把缺失伪装成正常空值。"""
    with pytest.raises(ValueError, match="非法的 Tushare 日期值"):
        parse_date("2024-13-45")


# --------------------------------------------------------------------------- #
# 按月分区
# --------------------------------------------------------------------------- #
def test_month_range_clamps_ends():
    out = month_range(pd.Timestamp("2024-01-15").date(), pd.Timestamp("2024-03-10").date())
    assert [ym for ym, _, _ in out] == ["2024-01", "2024-02", "2024-03"]
    assert out[0][1].day == 15  # 首月起点被夹到 start
    assert out[0][2].day == 31
    assert out[1][2].day == 29  # 2024 闰年
    assert out[-1][2].day == 10  # 末月终点被夹到 end


def test_month_range_single_month():
    d = pd.Timestamp("2024-05-07").date()
    assert month_range(d, d) == [("2024-05", d, d)]


# --------------------------------------------------------------------------- #
# 归一化：单位换算与派生字段
# --------------------------------------------------------------------------- #
def _stock_importer(tmp_raw_root):
    from gr_data.ingest.base import IngestContext
    from gr_data.ingest.tushare.importers.bars import StockBars1dImporter

    return StockBars1dImporter(conn=None, ctx=IngestContext(paths=tmp_raw_root))


def _write(paths, dataset, df):
    from gr_data.common.parquet import write_parquet

    write_parquet(df, paths.dataset_file("tushare", dataset, "2024-01"), append=False)


def _daily_df():
    return pd.DataFrame(
        [
            {
                "ts_code": "600000.SH",
                "trade_date": "20240102",
                "open": 10.0,
                "high": 10.8,
                "low": 9.9,
                "close": 10.5,
                "pre_close": 9.8,
                "vol": 1000.0,
                "amount": 10500.0,
            }
        ]
    )


def test_stock_units_and_adj_factor(tmp_raw_root, monkeypatch):
    """vol 手→股 (×100)，amount 千元→元 (×1000)，adj_factor 原样带出。"""
    _write(tmp_raw_root, "daily", _daily_df())
    _write(
        tmp_raw_root,
        "adj_factor",
        pd.DataFrame([{"ts_code": "600000.SH", "trade_date": "20240102", "adj_factor": 1.25}]),
    )
    _write(
        tmp_raw_root,
        "stk_limit",
        pd.DataFrame(
            [
                {
                    "ts_code": "600000.SH",
                    "trade_date": "20240102",
                    "pre_close": 9.8,
                    "up_limit": 10.78,
                    "down_limit": 8.82,
                }
            ]
        ),
    )

    imp = _stock_importer(tmp_raw_root)
    monkeypatch.setattr(imp, "_id_map", lambda: {"600000.SH": 42})
    df = imp.build()

    assert len(df) == 1
    row = df.iloc[0]
    assert row["volume"] == 1000.0 * 100
    assert row["amount"] == 10500.0 * 1000
    assert row["adj_factor"] == 1.25
    assert row["limit_up"] == 10.78
    assert row["instrument_id"] == 42
    assert row["source"] == "tushare"


def test_missing_adj_factor_raises(tmp_raw_root, monkeypatch):
    """复权因子在目标表是 NOT NULL，缺失不能用 1 兜底。"""
    _write(tmp_raw_root, "daily", _daily_df())
    _write(
        tmp_raw_root,
        "adj_factor",
        pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": "20240102", "adj_factor": 1.0}]),
    )

    imp = _stock_importer(tmp_raw_root)
    monkeypatch.setattr(imp, "_id_map", lambda: {"600000.SH": 42})
    with pytest.raises(ValueError, match="缺少 adj_factor"):
        imp.build()


def test_pre_close_mismatch_drops_limits(tmp_raw_root, monkeypatch):
    """daily 与 stk_limit 的 pre_close 基准不一致时，涨跌停价不可信，置 NULL。"""
    _write(tmp_raw_root, "daily", _daily_df())
    _write(
        tmp_raw_root,
        "adj_factor",
        pd.DataFrame([{"ts_code": "600000.SH", "trade_date": "20240102", "adj_factor": 1.0}]),
    )
    _write(
        tmp_raw_root,
        "stk_limit",
        pd.DataFrame(
            [
                {
                    "ts_code": "600000.SH",
                    "trade_date": "20240102",
                    "pre_close": 5.0,
                    "up_limit": 5.5,
                    "down_limit": 4.5,
                }
            ]
        ),
    )

    imp = _stock_importer(tmp_raw_root)
    monkeypatch.setattr(imp, "_id_map", lambda: {"600000.SH": 42})
    df = imp.build()
    assert pd.isna(df.iloc[0]["limit_up"])
    assert pd.isna(df.iloc[0]["limit_down"])
    # 行本身仍然入库——只是丢弃了不可信的附加字段
    assert df.iloc[0]["close"] == 10.5


def test_missing_stk_limit_leaves_null(tmp_raw_root, monkeypatch):
    """涨跌停价在目标表可为 NULL，缺失只警告，不阻断整批。"""
    _write(tmp_raw_root, "daily", _daily_df())
    _write(
        tmp_raw_root,
        "adj_factor",
        pd.DataFrame([{"ts_code": "600000.SH", "trade_date": "20240102", "adj_factor": 1.0}]),
    )

    imp = _stock_importer(tmp_raw_root)
    monkeypatch.setattr(imp, "_id_map", lambda: {"600000.SH": 42})
    df = imp.build()
    assert len(df) == 1
    assert pd.isna(df.iloc[0]["limit_up"])


def test_trading_status_from_suspensions(tmp_raw_root, monkeypatch):
    """S=停牌 → HALTED；同日同时有 R 则以复牌为准；无记录 → NORMAL。"""
    daily = pd.DataFrame(
        [
            {
                "ts_code": c,
                "trade_date": "20240102",
                "open": 10.0,
                "high": 10.8,
                "low": 9.9,
                "close": 10.5,
                "pre_close": 9.8,
                "vol": 1.0,
                "amount": 1.0,
            }
            for c in ("600000.SH", "000001.SZ", "600004.SH")
        ]
    )
    _write(tmp_raw_root, "daily", daily)
    _write(
        tmp_raw_root,
        "adj_factor",
        pd.DataFrame(
            [
                {"ts_code": c, "trade_date": "20240102", "adj_factor": 1.0}
                for c in ("600000.SH", "000001.SZ", "600004.SH")
            ]
        ),
    )
    _write(
        tmp_raw_root,
        "suspend_d",
        pd.DataFrame(
            [
                {"ts_code": "600000.SH", "trade_date": "20240102", "suspend_type": "S"},
                {"ts_code": "600004.SH", "trade_date": "20240102", "suspend_type": "S"},
                {"ts_code": "600004.SH", "trade_date": "20240102", "suspend_type": "R"},
            ]
        ),
    )

    imp = _stock_importer(tmp_raw_root)
    monkeypatch.setattr(imp, "_id_map", lambda: {"600000.SH": 1, "000001.SZ": 2, "600004.SH": 3})
    df = imp.build().set_index("instrument_id")

    assert df.loc[1, "trading_status"] == "HALTED"  # 仅停牌
    assert df.loc[2, "trading_status"] == "NORMAL"  # 无记录
    assert df.loc[3, "trading_status"] == "NORMAL"  # 停牌当日复牌


class _RecordingLog:
    """记录 warning 调用。项目 logger 不向 root 传播，caplog 抓不到。"""

    def __init__(self):
        self.warnings: list[str] = []

    def warning(self, msg, *args):
        self.warnings.append(msg % args if args else msg)

    def __getattr__(self, _name):
        return lambda *a, **k: None


def test_unknown_symbols_are_skipped_not_silently(tmp_raw_root, monkeypatch):
    """symbol_map 里没有的标的必须跳过（外键约束），但要留下可见的警告。"""
    _write(tmp_raw_root, "daily", _daily_df())
    _write(
        tmp_raw_root,
        "adj_factor",
        pd.DataFrame([{"ts_code": "600000.SH", "trade_date": "20240102", "adj_factor": 1.0}]),
    )

    imp = _stock_importer(tmp_raw_root)
    monkeypatch.setattr(imp, "_id_map", lambda: {})
    rec = _RecordingLog()
    monkeypatch.setattr(imp, "log", rec)

    df = imp.build()
    assert df.empty
    assert any("meta.symbol_map" in w and "600000.SH" in w for w in rec.warnings)


def test_future_units(tmp_raw_root, monkeypatch):
    """期货：amount 万元→元 (×10000)；vol / oi 保持「手」。"""
    from gr_data.ingest.base import IngestContext
    from gr_data.ingest.tushare.importers.bars import FutureBars1dImporter

    _write(
        tmp_raw_root,
        "fut_daily",
        pd.DataFrame(
            [
                {
                    "ts_code": "CU2401.SHF",
                    "trade_date": "20240102",
                    "pre_close": 68000.0,
                    "pre_settle": 68100.0,
                    "open": 68200.0,
                    "high": 68900.0,
                    "low": 68000.0,
                    "close": 68500.0,
                    "settle": 68400.0,
                    "vol": 5000.0,
                    "amount": 34250.0,
                    "oi": 12000.0,
                }
            ]
        ),
    )

    imp = FutureBars1dImporter(conn=None, ctx=IngestContext(paths=tmp_raw_root))
    monkeypatch.setattr(imp, "_id_map", lambda: {"CU2401.SHF": 7})
    row = imp.build().iloc[0]

    assert row["amount"] == 34250.0 * 10000  # 万元 → 元
    assert row["volume"] == 5000.0  # 手，不换算
    assert row["open_interest"] == 12000.0  # 手，不换算
    assert row["settle"] == 68400.0
    assert "adj_factor" not in imp.contract.columns


def _future_importer(tmp_raw_root):
    from gr_data.ingest.base import IngestContext
    from gr_data.ingest.tushare.importers.bars import FutureBars1dImporter

    return FutureBars1dImporter(conn=None, ctx=IngestContext(paths=tmp_raw_root))


def test_zero_prices_are_preserved_not_nulled(tmp_raw_root, monkeypatch):
    """0 是真实取值，必须原样保留——不能和「不知道」混为一谈。"""
    _write(
        tmp_raw_root,
        "fut_daily",
        pd.DataFrame(
            [
                {
                    "ts_code": "CU2401.SHF",
                    "trade_date": "20240102",
                    "pre_close": 0.0,
                    "pre_settle": 0.0,
                    "open": 0.0,
                    "high": 0.0,
                    "low": 0.0,
                    "close": 0.0,
                    "settle": 0.0,
                    "vol": 0.0,
                    "amount": 0.0,
                    "oi": 0.0,
                }
            ]
        ),
    )

    imp = _future_importer(tmp_raw_root)
    monkeypatch.setattr(imp, "_id_map", lambda: {"CU2401.SHF": 7})
    df = imp.build()
    assert len(df) == 1
    row = df.iloc[0]
    assert row["close"] == 0.0 and row["settle"] == 0.0
    assert row["volume"] == 0 and row["open_interest"] == 0


def test_invalid_prices_become_null(tmp_raw_root, monkeypatch):
    """非有限值与负数才是无效，转 NULL。"""
    _write(
        tmp_raw_root,
        "fut_daily",
        pd.DataFrame(
            [
                {
                    "ts_code": "CU2401.SHF",
                    "trade_date": "20240102",
                    "pre_close": float("nan"),
                    "pre_settle": -1.0,
                    "open": float("inf"),
                    "high": None,
                    "low": None,
                    "close": 68500.0,
                    "settle": 68400.0,
                    "vol": 5000.0,
                    "amount": 1.0,
                    "oi": 12000.0,
                }
            ]
        ),
    )

    imp = _future_importer(tmp_raw_root)
    monkeypatch.setattr(imp, "_id_map", lambda: {"CU2401.SHF": 7})
    row = imp.build().iloc[0]
    assert pd.isna(row["pre_close"])  # NaN
    assert pd.isna(row["pre_settle"])  # 负数
    assert pd.isna(row["open"])  # inf
    assert row["close"] == 68500.0  # 有效值不受影响


def test_future_settle_only_rows_kept(tmp_raw_root, monkeypatch):
    """当日无成交的合约没有 OHLC，但有结算价与持仓量——不能整行丢掉。"""
    _write(
        tmp_raw_root,
        "fut_daily",
        pd.DataFrame(
            [
                {
                    "ts_code": "BB2401.DCE",
                    "trade_date": "20240102",
                    "pre_close": None,
                    "pre_settle": 400.0,
                    "open": None,
                    "high": None,
                    "low": None,
                    "close": None,
                    "settle": 400.0,
                    "vol": 0.0,
                    "amount": 0.0,
                    "oi": 0.0,
                }
            ]
        ),
    )

    imp = _future_importer(tmp_raw_root)
    monkeypatch.setattr(imp, "_id_map", lambda: {"BB2401.DCE": 8})
    df = imp.build()
    assert len(df) == 1
    row = df.iloc[0]
    assert row["settle"] == 400.0
    assert pd.isna(row["open"]) and pd.isna(row["close"])


def test_index_close_only_rows_kept(tmp_raw_root, monkeypatch):
    """大量指数只发布收盘点位，不发布 OHLC——必须保留。"""
    from gr_data.ingest.base import IngestContext
    from gr_data.ingest.tushare.importers.bars import IndexBars1dImporter

    _write(
        tmp_raw_root,
        "index_daily",
        pd.DataFrame(
            [
                {
                    "ts_code": "H11001.CSI",
                    "trade_date": "20240102",
                    "open": None,
                    "high": None,
                    "low": None,
                    "close": 236.9688,
                    "pre_close": 237.0151,
                    "vol": None,
                    "amount": None,
                }
            ]
        ),
    )

    imp = IndexBars1dImporter(conn=None, ctx=IngestContext(paths=tmp_raw_root))
    monkeypatch.setattr(imp, "_id_map", lambda: {"H11001.CSI": 11})
    df = imp.build()
    assert len(df) == 1
    row = df.iloc[0]
    assert row["close"] == 236.9688
    assert pd.isna(row["open"]) and pd.isna(row["high"])


def test_index_no_adj_factor_no_limits(tmp_raw_root, monkeypatch):
    from gr_data.ingest.base import IngestContext
    from gr_data.ingest.tushare.importers.bars import IndexBars1dImporter

    _write(
        tmp_raw_root,
        "index_daily",
        pd.DataFrame(
            [
                {
                    "ts_code": "000300.SH",
                    "trade_date": "20240102",
                    "open": 3400.0,
                    "high": 3450.0,
                    "low": 3380.0,
                    "close": 3420.0,
                    "pre_close": 3390.0,
                    "vol": 200000.0,
                    "amount": 250000.0,
                }
            ]
        ),
    )

    imp = IndexBars1dImporter(conn=None, ctx=IngestContext(paths=tmp_raw_root))
    monkeypatch.setattr(imp, "_id_map", lambda: {"000300.SH": 9})
    row = imp.build().iloc[0]

    assert row["adj_factor"] == 1.0
    assert row["limit_up"] is None
    assert row["volume"] == 200000.0 * 100
    assert row["amount"] == 250000.0 * 1000
