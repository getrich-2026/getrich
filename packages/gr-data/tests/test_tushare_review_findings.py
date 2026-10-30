"""2026-10-22 人工审核 Tushare 链路时标 ⚠ 的疑点复现（只有测试，不改实现）。

每条用例断言的是**期望行为**，当前实现不满足，所以标 ``xfail(strict=True)``：
- 断言失败（AssertionError）记为 xfail，CI 保持绿色；
- 其他异常不算 xfail，会直接失败，避免用例本身写错被掩盖；
- 实现修复后变成 XPASS，strict 会让它失败，届时删掉对应的 xfail 标记即可。

编号对应审核清单里的条目号。已修复的条目（#12、#36、#46）去掉了 xfail，留作回归用例。
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pandas as pd
import pytest
from gr_data.raw.base import RawContext


def _finding(number: int, reason: str):
    return pytest.mark.xfail(
        strict=True, raises=AssertionError, reason=f"审核疑点 #{number}：{reason}"
    )


def _raised(fn, exc_type) -> bool:
    """调用 fn，只吞掉期望的异常类型；别的异常照常抛出，不被 xfail 掩盖。"""
    try:
        fn()
    except exc_type:
        return True
    return False


def _write(paths, dataset: str, df: pd.DataFrame, ym: str = "2024-01") -> None:
    from gr_data.common.parquet import write_parquet

    write_parquet(df, paths.dataset_file("tushare", dataset, ym), append=False)


def _ctx(tmp_raw_root) -> RawContext:
    return RawContext(
        paths=tmp_raw_root,
        rate_limit={"sleep_between_requests_sec": 0, "max_retries": 1, "retry_backoff_base_sec": 0},
        start_date=20240101,
    )


# --------------------------------------------------------------------------- #
# 公共层
# --------------------------------------------------------------------------- #
class _OwnershipCursor:
    def __init__(self, row):
        self._row = row
        self._result = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        self._result = self._row if sql.lstrip().upper().startswith("SELECT") else None

    def fetchone(self):
        return self._result


class _OwnershipConn:
    def __init__(self, row):
        self._row = row

    def cursor(self):
        return _OwnershipCursor(self._row)


@_finding(4, "docstring 说 force 转移归属会记日志，代码里没有任何日志")
def test_force_ownership_transfer_is_logged(caplog):
    from gr_data.common.ownership import OwnershipManager

    caplog.set_level(logging.DEBUG)
    conn = _OwnershipConn(("market.stock_bar_1d", "ricequant", "ingest"))
    OwnershipManager(conn).claim("market.stock_bar_1d", "tushare", force=True)

    assert any("ricequant" in r.getMessage() for r in caplog.records)


@_finding(5, "日历文件损坏时报「缺少交易日历」，把坏文件说成缺文件")
def test_corrupt_calendar_reported_as_corrupt(tmp_raw_root, fake_tushare):
    from gr_data.common.parquet import CorruptRawError
    from gr_data.raw.tushare import REGISTRY

    path = tmp_raw_root.dataset_file("tushare", "calendar", "SSE")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a parquet file")
    fetcher = REGISTRY["daily"](fake_tushare, _ctx(tmp_raw_root))

    with pytest.raises(Exception) as exc:
        fetcher._trading_days()
    assert isinstance(exc.value, CorruptRawError)


# --------------------------------------------------------------------------- #
# raw 抓取
# --------------------------------------------------------------------------- #
def _daily_fetcher(tmp_raw_root, fake_tushare, monkeypatch, empty_days: set[str]):
    """日历已抓、``empty_days`` 里的交易日 daily 返回空响应的 fetcher（集合可在用例中改动）。"""
    from gr_data.raw.tushare import REGISTRY

    ctx = _ctx(tmp_raw_root)
    REGISTRY["calendar"](fake_tushare, ctx).fetch("init")
    original = fake_tushare._daily
    monkeypatch.setattr(
        fake_tushare,
        "_daily",
        lambda **p: pd.DataFrame() if p.get("trade_date") in empty_days else original(**p),
    )
    return REGISTRY["daily"](fake_tushare, ctx)


def _set_today(monkeypatch, value: int) -> None:
    from gr_data.raw.tushare.fetchers import market

    monkeypatch.setattr(market, "today_int", lambda: value)


def _daily_path(tmp_raw_root):
    return tmp_raw_root.dataset_file("tushare", "daily", "2024-01")


def test_new_month_past_empty_trading_day_rejected(tmp_raw_root, fake_tushare, monkeypatch):
    """#12：没有旧分区可比时，过去交易日的空响应也必须拒绝，不写出缺一天的分区。"""
    _set_today(monkeypatch, 20240131)
    fetcher = _daily_fetcher(tmp_raw_root, fake_tushare, monkeypatch, {"20240103"})

    with pytest.raises(ValueError, match="过去的交易日返回空响应"):
        fetcher.fetch("init")
    assert not _daily_path(tmp_raw_root).exists()


def test_today_empty_day_filled_by_next_update(tmp_raw_root, fake_tushare, monkeypatch, caplog):
    """#12：今天的空响应视为尚未发布，照常写出其余日期；次日 update 重抓最新月补齐。"""
    empty = {"20240103"}
    _set_today(monkeypatch, 20240103)
    fetcher = _daily_fetcher(tmp_raw_root, fake_tushare, monkeypatch, empty)
    caplog.set_level(logging.INFO, logger="gr_data.raw.tushare.daily")

    fetcher.fetch("init")
    written = pd.read_parquet(_daily_path(tmp_raw_root))
    assert set(written["trade_date"]) == {"20240102"}
    assert any("not yet published" in r.getMessage() for r in caplog.records)

    empty.clear()  # 供应商当晚发布
    _set_today(monkeypatch, 20240104)
    fetcher.fetch("update")
    assert set(pd.read_parquet(_daily_path(tmp_raw_root))["trade_date"]) == {
        "20240102",
        "20240103",
    }


def test_existing_partition_missing_past_day_rejected(tmp_raw_root, fake_tushare, monkeypatch):
    """#12：旧分区本来就缺的那天，成为过去后仍为空响应也拒绝；旧的「拒绝覆盖」拦不住这种。"""
    _set_today(monkeypatch, 20240103)
    fetcher = _daily_fetcher(tmp_raw_root, fake_tushare, monkeypatch, {"20240103"})
    fetcher.fetch("init")
    before = _daily_path(tmp_raw_root).read_bytes()

    _set_today(monkeypatch, 20240104)
    with pytest.raises(ValueError, match="过去的交易日返回空响应"):
        fetcher.fetch("update")
    assert _daily_path(tmp_raw_root).read_bytes() == before


# --------------------------------------------------------------------------- #
# 参考数据
# --------------------------------------------------------------------------- #
def _instruments_importer(tmp_raw_root):
    from gr_data.ingest.base import IngestContext
    from gr_data.ingest.tushare.importers.reference import InstrumentsImporter

    return InstrumentsImporter(conn=None, ctx=IngestContext(paths=tmp_raw_root))


@_finding(26, "未知 list_status 被默认当成 active，没有报错")
def test_unknown_list_status_rejected(tmp_raw_root):
    raw = pd.DataFrame(
        [
            {
                "ts_code": "600000.SH",
                "name": "浦发银行",
                "list_status": "X",
                "list_date": "19991110",
                "delist_date": None,
            }
        ]
    )
    imp = _instruments_importer(tmp_raw_root)

    assert _raised(lambda: imp._build_stock(raw), ValueError)


def test_expired_future_not_active(tmp_raw_root):
    raw = pd.DataFrame(
        [
            {
                "ts_code": "CU2001.SHF",
                "name": "沪铜2001",
                "list_date": "20190116",
                "delist_date": "20200115",
            }
        ]
    )
    out = _instruments_importer(tmp_raw_root)._build_future(raw)

    assert out.iloc[0]["status"] != "active"


def test_calendar_invalid_is_open_rejected(tmp_raw_root):
    from gr_data.ingest.base import IngestContext
    from gr_data.ingest.tushare.importers.reference import CalendarImporter

    raw = pd.DataFrame(
        [
            {"cal_date": "20240102", "is_open": "abc", "pretrade_date": "20231229"},
            {"cal_date": "20240103", "is_open": 1, "pretrade_date": "20240102"},
        ]
    )
    imp = CalendarImporter(conn=None, ctx=IngestContext(paths=tmp_raw_root))

    assert _raised(lambda: imp._build_one(raw, "XSHG"), ValueError)


# --------------------------------------------------------------------------- #
# 股票日线
# --------------------------------------------------------------------------- #
def _daily_row(**overrides) -> dict:
    row = {
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
    row.update(overrides)
    return row


def _stock_importer_with(tmp_raw_root, monkeypatch, daily: pd.DataFrame):
    from gr_data.ingest.base import IngestContext
    from gr_data.ingest.tushare.importers.market import StockBars1dImporter

    _write(tmp_raw_root, "daily", daily)
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
                    "up_limit": 10.78,
                    "down_limit": 8.82,
                }
            ]
        ),
    )
    imp = StockBars1dImporter(conn=None, ctx=IngestContext(paths=tmp_raw_root))
    monkeypatch.setattr(imp, "_id_map", lambda: {"600000.SH": 42})
    return imp


@pytest.mark.parametrize(
    "overrides",
    [{"vol": None}, {"vol": "abc"}, {"vol": float("inf")}, {"amount": None}],
)
def test_stock_invalid_volume_or_amount_rejected(tmp_raw_root, monkeypatch, overrides):
    """#36：成交量／成交额缺失、非数值或非有限时硬失败，不静默写成 NULL。"""
    daily = pd.DataFrame([_daily_row(**overrides)])
    imp = _stock_importer_with(tmp_raw_root, monkeypatch, daily)

    # 非数值在严格解析时即被拒绝（报出具体列），缺失与非有限值由后续量额检查拒绝。
    with pytest.raises(ValueError, match=r"成交量或成交额|daily\.(vol|amount) 含无法解析"):
        imp.build()


def test_stock_zero_volume_kept(tmp_raw_root, monkeypatch):
    """#36：0 是真实取值（无成交），不能被新校验误拒。"""
    daily = pd.DataFrame([_daily_row(vol=0.0, amount=0.0)])
    row = _stock_importer_with(tmp_raw_root, monkeypatch, daily).build().iloc[0]

    assert row["volume"] == 0
    assert row["amount"] == 0.0


@_finding(37, "收盘价高于最高价的 bar 照常入库")
def test_stock_close_outside_high_low_rejected(tmp_raw_root, monkeypatch):
    imp = _stock_importer_with(tmp_raw_root, monkeypatch, pd.DataFrame([_daily_row(close=11.0)]))

    assert _raised(imp.build, ValueError)


# --------------------------------------------------------------------------- #
# 指数
# --------------------------------------------------------------------------- #
def _index_importer_with(tmp_raw_root, monkeypatch, rows: list[dict]):
    from gr_data.ingest.base import IngestContext
    from gr_data.ingest.tushare.importers.market import IndexBars1dImporter

    _write(tmp_raw_root, "index_daily", pd.DataFrame(rows))
    imp = IndexBars1dImporter(conn=None, ctx=IngestContext(paths=tmp_raw_root))
    monkeypatch.setattr(imp, "_id_map", lambda: {"000300.SH": 11, "H11001.CSI": 12})
    return imp


def _index_row(**overrides) -> dict:
    row = {
        "ts_code": "000300.SH",
        "trade_date": "20240102",
        "open": 3400.0,
        "high": 3450.0,
        "low": 3390.0,
        "close": 3430.0,
        "pre_close": 3410.0,
        "vol": 100.0,
        "amount": 2000.0,
    }
    row.update(overrides)
    return row


class _EmptyQueryConn:
    """查询一律返回空结果；换码合并遇到重复键时会查 meta.instruments。"""

    def cursor(self):
        cursor = MagicMock()
        cursor.__enter__.return_value.fetchall.return_value = []
        return cursor


def test_index_duplicates_with_whitespace_collapsed(tmp_raw_root, monkeypatch):
    rows = [_index_row(), _index_row(ts_code="000300.SH ", close=3431.0)]
    imp = _index_importer_with(tmp_raw_root, monkeypatch, rows)
    imp.conn = _EmptyQueryConn()
    out = imp.build()

    assert not out.duplicated(subset=["instrument_id", "dt"]).any()


def test_index_dropped_rows_raise_soft_warning(tmp_raw_root, monkeypatch):
    rows = [_index_row(), _index_row(ts_code="H11001.CSI", close=None)]
    imp = _index_importer_with(tmp_raw_root, monkeypatch, rows)
    out = imp.build()

    assert len(out) == 1  # 前提：无收盘价的行确实被丢弃
    assert imp.collect_soft_warnings()


# --------------------------------------------------------------------------- #
# daily_basic／估值
# --------------------------------------------------------------------------- #
def _daily_basic_raw_without(*columns: str) -> pd.DataFrame:
    row = {
        "ts_code": "600000.SH",
        "trade_date": "20240102",
        "close": 10.5,
        "turnover_rate": 1.25,
        "turnover_rate_f": 1.5,
        "volume_ratio": 0.9,
        "pe": 12.0,
        "pe_ttm": 11.5,
        "pb": 1.2,
        "ps": 3.0,
        "ps_ttm": 2.9,
        "dv_ratio": 2.5,
        "dv_ttm": 2.4,
        "total_share": 100000.0,
        "float_share": 80000.0,
        "free_share": 70000.0,
        "total_mv": 12000.0,
        "circ_mv": 8000.0,
        "limit_status": 0,
    }
    return pd.DataFrame([{k: v for k, v in row.items() if k not in columns}])


def test_one_partition_missing_column_rejected(tmp_raw_root, monkeypatch):
    """#46：只有某个月分区缺列时，拼接后的列表面齐全，必须按分区逐个校验才拦得住。"""
    from gr_data.ingest.base import IngestContext
    from gr_data.ingest.tushare.importers.market import ValuationImporter

    _write(tmp_raw_root, "daily_basic", _daily_basic_raw_without())
    february = _daily_basic_raw_without("pe_ttm").assign(trade_date="20240201")
    _write(tmp_raw_root, "daily_basic", february, ym="2024-02")
    imp = ValuationImporter(conn=None, ctx=IngestContext(paths=tmp_raw_root))
    monkeypatch.setattr(imp, "_id_map", lambda: {"600000.SH": 42})

    with pytest.raises(ValueError, match=r"daily_basic\[2024-02\] 缺少字段.*pe_ttm"):
        imp.build()


@pytest.mark.parametrize(
    "missing",
    ["total_mv", "circ_mv", "pb", "pe_ttm", "total_share", "turnover_rate", "limit_status"],
)
def test_valuation_missing_column_rejected(tmp_raw_root, monkeypatch, missing):
    """#46：估值缺列时硬失败；pe_ttm 的 NULL 只能来自源值（亏损股），不能来自缺列。"""
    from gr_data.ingest.base import IngestContext
    from gr_data.ingest.tushare.importers.market import ValuationImporter

    _write(tmp_raw_root, "daily_basic", _daily_basic_raw_without(missing))
    imp = ValuationImporter(conn=None, ctx=IngestContext(paths=tmp_raw_root))
    monkeypatch.setattr(imp, "_id_map", lambda: {"600000.SH": 42})

    with pytest.raises(ValueError, match=f"缺少字段.*{missing}"):
        imp.build()
