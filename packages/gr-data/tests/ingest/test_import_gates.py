"""导入最低可靠性门禁：坏文件、缺分区、未知代码硬失败，软告警与退出码。"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from gr_data.common.parquet import write_parquet
from gr_data.ingest.base import IngestContext


MONTH = "2024-01"
DAY = "20240102"


def _write(paths, dataset, df, month=MONTH):
    write_parquet(df, paths.dataset_file("tushare", dataset, month), append=False)


def _daily(codes=("600000.SH",), day=DAY):
    return pd.DataFrame(
        [
            {
                "ts_code": c,
                "trade_date": day,
                "open": 10.0,
                "high": 10.8,
                "low": 9.9,
                "close": 10.5,
                "pre_close": 9.8,
                "vol": 1000.0,
                "amount": 10500.0,
            }
            for c in codes
        ]
    )


def _adj(codes=("600000.SH",), day=DAY):
    return pd.DataFrame([{"ts_code": c, "trade_date": day, "adj_factor": 1.0} for c in codes])


def _limits(codes=("600000.SH",), day=DAY):
    return pd.DataFrame(
        [
            {
                "ts_code": c,
                "trade_date": day,
                "pre_close": 9.8,
                "up_limit": 10.78,
                "down_limit": 8.82,
            }
            for c in codes
        ]
    )


def _stock_month(paths, codes=("600000.SH",), month=MONTH, day=DAY, limits=True):
    _write(paths, "daily", _daily(codes, day), month)
    _write(paths, "adj_factor", _adj(codes, day), month)
    if limits:
        _write(paths, "stk_limit", _limits(codes, day), month)


def _stock_importer(paths, months=None, id_map=None):
    from gr_data.ingest.tushare.importers.market import StockBars1dImporter

    imp = StockBars1dImporter(conn=None, ctx=IngestContext(paths=paths, months=months))
    imp._id_map = lambda: id_map if id_map is not None else {"600000.SH": 1}
    # 离线用例不连库：停复牌证据为空，等同于库内尚无覆盖。
    imp._status_evidence = lambda ids, days: (pd.DataFrame(), set())
    return imp


# --------------------------------------------------------------------------- #
# 1. 严格读取
# --------------------------------------------------------------------------- #
def test_corrupt_partition_raises_instead_of_missing(tmp_raw_root):
    from gr_data.common.parquet import CorruptRawError

    _stock_month(tmp_raw_root)
    _stock_month(tmp_raw_root, month="2024-02", day="20240201")
    bad = tmp_raw_root.dataset_file("tushare", "daily", "2024-02")
    bad.write_bytes(bad.read_bytes()[:40])
    with pytest.raises(CorruptRawError, match=r"daily/2024-02\.parquet"):
        _stock_importer(tmp_raw_root).build()
    assert bad.exists()  # 不删除、不覆盖证据


def test_corrupt_reference_file_raises(tmp_raw_root):
    from gr_data.common.parquet import CorruptRawError
    from gr_data.ingest.tushare.adapter import TushareAdapter

    path = tmp_raw_root.dataset_file("tushare", "calendar", "SSE")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not parquet")
    with pytest.raises(CorruptRawError):
        TushareAdapter(tmp_raw_root).read_calendar("SSE")


def test_stray_tmp_files_are_not_read_as_months(tmp_raw_root):
    from gr_data.ingest.tushare.adapter import TushareAdapter

    _stock_month(tmp_raw_root)
    stray = tmp_raw_root.dataset_file("tushare", "daily", "2024-01.tmp-deadbeef")
    write_parquet(_daily(), stray)
    adapter = TushareAdapter(tmp_raw_root)
    assert adapter.list_months("daily") == [MONTH]
    assert any("2024-01.tmp-deadbeef" in n for n in adapter.notices)

    imp = _stock_importer(tmp_raw_root)
    assert len(imp.build()) == 1
    assert any("tmp-deadbeef" in w for w in imp.collect_soft_warnings())


# --------------------------------------------------------------------------- #
# 2. 必需分区
# --------------------------------------------------------------------------- #
def test_requested_month_without_partition_fails(tmp_raw_root):
    from gr_data.ingest.base import IngestGateError

    _stock_month(tmp_raw_root)
    with pytest.raises(IngestGateError, match=r"daily.*2024-02"):
        _stock_importer(tmp_raw_root, months=(MONTH, "2024-02")).build()


def test_missing_stk_limit_month_fails_instead_of_null(tmp_raw_root):
    from gr_data.ingest.base import IngestGateError

    _stock_month(tmp_raw_root, limits=False)
    with pytest.raises(IngestGateError, match=r"stk_limit.*2024-01"):
        _stock_importer(tmp_raw_root).build()


def test_no_partitions_at_all_fails(tmp_raw_root):
    from gr_data.ingest.base import IngestGateError

    with pytest.raises(IngestGateError, match="daily"):
        _stock_importer(tmp_raw_root).build()


def test_valuation_requires_requested_month(tmp_raw_root):
    from gr_data.ingest.base import IngestGateError
    from gr_data.ingest.tushare.importers.market import ValuationImporter

    imp = ValuationImporter(conn=None, ctx=IngestContext(paths=tmp_raw_root, months=(MONTH,)))
    imp._id_map = lambda: {"600000.SH": 1}
    with pytest.raises(IngestGateError, match=r"daily_basic.*2024-01"):
        imp.build()


def test_partial_limit_keys_are_soft_warning(tmp_raw_root):
    _write(tmp_raw_root, "daily", _daily(("600000.SH", "000001.SZ")))
    _write(tmp_raw_root, "adj_factor", _adj(("600000.SH", "000001.SZ")))
    _write(tmp_raw_root, "stk_limit", _limits(("600000.SH",)))
    imp = _stock_importer(tmp_raw_root, id_map={"600000.SH": 1, "000001.SZ": 2})
    df = imp.build().set_index("instrument_id")
    assert pd.isna(df.loc[2, "limit_up"])
    assert any("limit" in w for w in imp.collect_soft_warnings())


@pytest.mark.parametrize("with_limit_row", [True, False])
def test_first_listing_day_without_pre_close_is_not_soft_warning(tmp_raw_root, with_limit_row):
    """首日无前收盘是真实语义（info + data_quality_check），不能绕道变成软告警、退出码 3。"""
    codes = ("600000.SH", "920001.BJ")  # 后者为首日上市
    daily = _daily(codes)
    daily.loc[daily["ts_code"] == "920001.BJ", "pre_close"] = float("nan")
    _write(tmp_raw_root, "daily", daily)
    _write(tmp_raw_root, "adj_factor", _adj(codes))
    limits = _limits(codes if with_limit_row else codes[:1])
    if with_limit_row:
        limits.loc[limits["ts_code"] == "920001.BJ", ["pre_close", "up_limit", "down_limit"]] = (
            float("nan")
        )
    _write(tmp_raw_root, "stk_limit", limits)
    imp = _stock_importer(tmp_raw_root, id_map={"600000.SH": 1, "920001.BJ": 2})
    imp._record_missing_price = lambda *a: None
    df = imp.build().set_index("instrument_id")
    assert pd.isna(df.loc[2, "limit_up"]) and df.loc[1, "limit_up"] == 10.78
    assert imp.collect_soft_warnings() == []


# --------------------------------------------------------------------------- #
# 3. 未知代码
# --------------------------------------------------------------------------- #
def test_unknown_symbols_fail_with_samples(tmp_raw_root):
    from gr_data.ingest.base import IngestGateError

    _stock_month(tmp_raw_root)
    with pytest.raises(IngestGateError, match=r"600000\.SH"):
        _stock_importer(tmp_raw_root, id_map={}).build()


# --------------------------------------------------------------------------- #
# 4. 参考数据
# --------------------------------------------------------------------------- #
def _stock_basic():
    return pd.DataFrame(
        [
            {
                "ts_code": "600000.SH",
                "name": "浦发银行",
                "list_status": "L",
                "list_date": "19991110",
                "delist_date": None,
            }
        ]
    )


def test_missing_stock_instruments_fails(tmp_raw_root):
    from gr_data.ingest.base import IngestGateError
    from gr_data.ingest.tushare.importers.reference import InstrumentsImporter

    with pytest.raises(IngestGateError, match="stock"):
        InstrumentsImporter(conn=None, ctx=IngestContext(paths=tmp_raw_root)).build()


def test_missing_index_instruments_is_soft(tmp_raw_root):
    from gr_data.ingest.tushare.importers.reference import InstrumentsImporter

    write_parquet(_stock_basic(), tmp_raw_root.dataset_file("tushare", "instruments", "stock"))
    imp = InstrumentsImporter(conn=None, ctx=IngestContext(paths=tmp_raw_root))
    assert len(imp.build()) == 1
    warnings = imp.collect_soft_warnings()
    assert any("index" in w for w in warnings) and any("future" in w for w in warnings)


def test_missing_calendar_exchange_fails(tmp_raw_root):
    from gr_data.ingest.base import IngestGateError
    from gr_data.ingest.tushare.importers.reference import CalendarImporter

    cal = pd.DataFrame([{"exchange": "SSE", "cal_date": DAY, "is_open": 1, "pretrade_date": None}])
    write_parquet(cal, tmp_raw_root.dataset_file("tushare", "calendar", "SSE"))
    with pytest.raises(IngestGateError, match="SZSE"):
        CalendarImporter(conn=None, ctx=IngestContext(paths=tmp_raw_root)).build()


# --------------------------------------------------------------------------- #
# 5. 编排与退出码（不连库）
# --------------------------------------------------------------------------- #
def _cfg(tmp_raw_root, ingest):
    from gr_data.config.pipeline import Config

    return Config(
        {"paths": {"raw_root": str(tmp_raw_root.root)}, "enabled": {"ingest": {"tushare": ingest}}}
    )


def test_unknown_importer_rejected_before_connecting(tmp_raw_root):
    from gr_data.ingest import UnknownImporterError, plan_importers

    # 继承 RuntimeError：cli.main 按配置问题返回退出码 2。
    assert issubclass(UnknownImporterError, RuntimeError)
    with pytest.raises(UnknownImporterError, match="no_such_importer"):
        plan_importers("tushare", _cfg(tmp_raw_root, ["instruments", "no_such_importer"]))


def _cli_args(**kw):
    import argparse

    base = {"provider": "tushare", "only": None, "force_ownership": False, "months": None}
    return argparse.Namespace(**{**base, **kw})


def test_cli_unknown_importer_does_not_connect(tmp_raw_root, monkeypatch):
    from gr_data import cli
    from gr_data.ingest import UnknownImporterError

    monkeypatch.setattr(cli, "connect", lambda *a, **k: pytest.fail("connected to PG"))
    with pytest.raises(UnknownImporterError, match="bogus"):
        cli.cmd_ingest(_cli_args(only="bogus"), _cfg(tmp_raw_root, ["instruments"]))


class _NullConn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_cli_exit_codes(tmp_raw_root, monkeypatch):
    from gr_data import cli, ingest
    from gr_data.ingest.base import IngestResult

    cfg = _cfg(tmp_raw_root, ["instruments"])
    monkeypatch.setattr(cli, "connect", lambda *a, **k: _NullConn())
    monkeypatch.setattr(cli, "_pg", lambda cfg: None)

    clean = [IngestResult("instruments", "meta.instruments", 1, [])]
    monkeypatch.setattr(ingest, "run_provider", lambda *a, **k: clean)
    assert cli.cmd_ingest(_cli_args(), cfg) == 0

    soft = [IngestResult("instruments", "meta.instruments", 1, ["instruments[index] missing"])]
    monkeypatch.setattr(ingest, "run_provider", lambda *a, **k: soft)
    assert cli.cmd_ingest(_cli_args(), cfg) == 3

    def failing(*a, **k):
        raise ingest.IngestRunError("tushare", "stock_bar_1d", clean, ["daily_basic"], "boom")

    monkeypatch.setattr(ingest, "run_provider", failing)
    assert cli.cmd_ingest(_cli_args(), cfg) == 1


class _DeadConn:
    """连接已断：rollback 也抛断连错误。"""

    def rollback(self):
        import psycopg

        raise psycopg.OperationalError("connection is closed")

    def cursor(self):
        import psycopg

        raise psycopg.OperationalError("connection is closed")


class _Recorder:
    def __init__(self):
        self.calls: list[dict] = []

    def error(self, msg, *args, **kwargs):
        self.calls.append({"msg": msg % args, **kwargs})

    def __getattr__(self, _name):
        return lambda *a, **k: None


def _failing_registry(exc):
    class _Boom:
        DATASET = "boom"

        def __init__(self, *a, **k):
            pass

        def run(self):
            raise exc

    return {"boom": _Boom}, {}


@pytest.mark.parametrize(
    "exc,expect_trace",
    [(KeyError("bug"), True), (None, False)],
    ids=["unexpected-bug", "gate-error"],
)
def test_failure_contract_survives_dead_connection(tmp_raw_root, monkeypatch, exc, expect_trace):
    """记录失败流水时连接已断，仍抛 IngestRunError；程序缺陷保留堆栈，门禁失败只记摘要。"""
    from gr_data import ingest
    from gr_data.ingest.base import IngestGateError

    error = exc if exc is not None else IngestGateError("daily: missing raw partitions")
    monkeypatch.setattr(ingest, "_registry_groups", lambda provider: _failing_registry(error))
    recorder = _Recorder()
    monkeypatch.setattr(ingest, "log", recorder)
    with pytest.raises(ingest.IngestRunError) as info:
        ingest.run_provider("yinhe", _DeadConn(), _cfg(tmp_raw_root, []), only=["boom"])
    assert info.value.__cause__ is error
    failure = next(c for c in recorder.calls if c["msg"].startswith("Ingest failed"))
    assert bool(failure.get("exc_info")) is expect_trace


# --------------------------------------------------------------------------- #
# 6. PG：硬失败不写库、记录失败、停止后续 importer
# --------------------------------------------------------------------------- #
def _seed_reference(pg_conn):
    pg_conn.execute(
        "INSERT INTO meta.instruments (symbol,asset,exchange,list_date) "
        "VALUES ('600000.SH','stock','XSHG','2000-01-01')"
    )
    iid = pg_conn.execute("SELECT instrument_id FROM meta.instruments").fetchone()[0]
    pg_conn.execute(
        "INSERT INTO meta.symbol_map (instrument_id,source,source_symbol) "
        "VALUES (%s,'tushare','600000.SH')",
        (iid,),
    )
    pg_conn.commit()
    return iid


@pytest.mark.integration
def test_failure_is_recorded_and_stops_remaining_importers(pg_conn, tmp_raw_root, monkeypatch):
    from gr_data import ingest
    from gr_data.config.pipeline import Config

    # Config.raw_root 优先读环境变量；其他用例可能已把本机 .env 装进 os.environ。
    monkeypatch.setenv("RAW_PARQUET_ROOT", str(tmp_raw_root.root))
    _seed_reference(pg_conn)
    _stock_month(tmp_raw_root, limits=False)  # 缺 stk_limit → stock_bar_1d 硬失败
    _write(
        tmp_raw_root,
        "suspend_d",
        pd.DataFrame(columns=["ts_code", "trade_date", "suspend_type", "suspend_timing"]),
    )
    from gr_data.raw.tushare.suspension_store import publish_coverage

    publish_coverage(tmp_raw_root.dataset_file("tushare", "suspend_d", MONTH), [date(2024, 1, 2)])
    cfg = Config({"paths": {"raw_root": str(tmp_raw_root.root)}})
    with pytest.raises(ingest.IngestRunError) as info:
        ingest.run_provider(
            "tushare", pg_conn, cfg, only=["suspend_d", "stock_bar_1d", "adj_factor_ts"]
        )
    err = info.value
    assert err.importer == "stock_bar_1d"
    assert [r.dataset for r in err.completed] == ["suspend_d"]
    assert err.skipped == ["adj_factor_ts"]
    rows = pg_conn.execute(
        "SELECT dataset_name, status, error FROM ops.etl_job_run ORDER BY run_id"
    ).fetchall()
    assert [(r[0], r[1]) for r in rows] == [("suspend_d", "success"), ("stock_bar_1d", "failed")]
    assert "stk_limit" in rows[1][2]
    assert pg_conn.execute("SELECT count(*) FROM market.stock_bar_1d").fetchone()[0] == 0
    assert pg_conn.execute("SELECT count(*) FROM market.adj_factor_ts").fetchone()[0] == 0


@pytest.mark.integration
def test_strict_quality_issue_blocks_write(pg_conn, tmp_raw_root, monkeypatch):
    from gr_data.ingest.base import IngestGateError
    from gr_data.ingest.tushare.importers.market import AdjFactorTsImporter

    _seed_reference(pg_conn)
    imp = AdjFactorTsImporter(pg_conn, IngestContext(paths=tmp_raw_root))
    monkeypatch.setattr(
        imp,
        "build",
        lambda: pd.DataFrame(
            {
                "instrument_id": [1, 1],
                "trading_day": [date(2024, 1, 2)] * 2,
                "adj_factor": [1.0, 1.0],
                "source": ["tushare"] * 2,
            }
        ).reindex(columns=list(imp.contract.columns)),
    )
    with pytest.raises(IngestGateError, match="重复主键|duplicate"):
        imp.run()
    pg_conn.rollback()
    assert pg_conn.execute("SELECT count(*) FROM market.adj_factor_ts").fetchone()[0] == 0


# --------------------------------------------------------------------------- #
# 7. P2-2：bar 状态只从库内事件与覆盖推导
# --------------------------------------------------------------------------- #
def _suspend_partition(paths, rows, days):
    from gr_data.raw.tushare.suspension_store import publish_coverage

    path = paths.dataset_file("tushare", "suspend_d", MONTH)
    write_parquet(
        pd.DataFrame(rows, columns=["ts_code", "trade_date", "suspend_type", "suspend_timing"]),
        path,
    )
    publish_coverage(path, days)


@pytest.mark.integration
def test_bar_status_comes_from_db_and_rejects_stale_db(pg_conn, tmp_raw_root):
    from gr_data.ingest.base import IngestGateError
    from gr_data.ingest.tushare.importers.market import StockBars1dImporter
    from gr_data.ingest.tushare.importers.suspensions import SuspensionImporter

    iid = _seed_reference(pg_conn)
    ctx = IngestContext(paths=tmp_raw_root, months=(MONTH,))
    _stock_month(tmp_raw_root)
    _suspend_partition(tmp_raw_root, [["600000.SH", DAY, "S", "09:30-10:00"]], [date(2024, 1, 2)])
    SuspensionImporter(pg_conn, ctx).run()
    StockBars1dImporter(pg_conn, ctx).run()
    status = pg_conn.execute(
        "SELECT trading_status FROM market.stock_bar_1d WHERE instrument_id=%s", (iid,)
    ).fetchone()[0]
    assert status == "INTRADAY_HALTED"

    # raw 停复牌更新了但库内事件未重导：不能用旧事件静默写状态。
    _suspend_partition(tmp_raw_root, [], [date(2024, 1, 2)])
    with pytest.raises(IngestGateError, match="suspend_d"):
        StockBars1dImporter(pg_conn, ctx).run()
    pg_conn.rollback()
    SuspensionImporter(pg_conn, ctx).run()
    StockBars1dImporter(pg_conn, ctx).run()
    status = pg_conn.execute(
        "SELECT trading_status FROM market.stock_bar_1d WHERE instrument_id=%s", (iid,)
    ).fetchone()[0]
    assert status == "NORMAL"


@pytest.mark.integration
def test_bar_status_unknown_without_any_coverage(pg_conn, tmp_raw_root):
    from gr_data.ingest.tushare.importers.market import StockBars1dImporter

    iid = _seed_reference(pg_conn)
    _stock_month(tmp_raw_root)
    StockBars1dImporter(pg_conn, IngestContext(paths=tmp_raw_root, months=(MONTH,))).run()
    status = pg_conn.execute(
        "SELECT trading_status FROM market.stock_bar_1d WHERE instrument_id=%s", (iid,)
    ).fetchone()[0]
    assert status == "UNKNOWN"


@pytest.mark.integration
def test_bar_status_rejects_raw_proof_missing_from_db(pg_conn, tmp_raw_root):
    """raw 已有停复牌凭据但库内从未导入：不能把这些日期写成 UNKNOWN 了事。"""
    from gr_data.ingest.base import IngestGateError
    from gr_data.ingest.tushare.importers.market import StockBars1dImporter

    _seed_reference(pg_conn)
    _stock_month(tmp_raw_root)
    _suspend_partition(tmp_raw_root, [], [date(2024, 1, 2)])
    with pytest.raises(IngestGateError, match="suspend_d"):
        StockBars1dImporter(pg_conn, IngestContext(paths=tmp_raw_root, months=(MONTH,))).run()


@pytest.mark.integration
def test_suspension_import_reports_stray_files(pg_conn, tmp_raw_root):
    from gr_data.ingest.tushare.importers.suspensions import SuspensionImporter

    _seed_reference(pg_conn)
    _suspend_partition(tmp_raw_root, [], [date(2024, 1, 2)])
    stray = tmp_raw_root.dataset_file("tushare", "suspend_d", "2024-01.tmp-deadbeef")
    stray.write_bytes(b"x")
    result = SuspensionImporter(pg_conn, IngestContext(paths=tmp_raw_root)).run()
    assert any("tmp-deadbeef" in w for w in result.warnings)


def test_registry_orders_suspensions_before_bars():
    from gr_data.ingest.tushare import REGISTRY

    names = list(REGISTRY)
    assert names.index("suspend_d") < names.index("stock_bar_1d")
