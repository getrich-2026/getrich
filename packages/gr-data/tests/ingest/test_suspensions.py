"""D-023：事件覆盖、四态、合法空与撤销重导回归。"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from gr_data.common.parquet import write_parquet
from gr_data.common.trading_status import resolve_trading_status
from gr_data.ingest.base import IngestContext
from gr_data.ingest.tushare.importers.market import StockBars1dImporter
from gr_data.ingest.tushare.importers.suspensions import SuspensionImporter
from gr_data.ingest.tushare.suspensions import read_suspensions
from gr_data.raw.tushare.suspension_store import normalize_events, publish_coverage


DAY = date(2024, 1, 2)
COLUMNS = ["ts_code", "trade_date", "suspend_type", "suspend_timing"]


def _partition(paths, rows, *, month="2024-01", days=None):
    path = paths.dataset_file("tushare", "suspend_d", month)
    write_parquet(pd.DataFrame(rows, columns=COLUMNS), path)
    publish_coverage(path, days or [DAY])
    return path


@pytest.mark.parametrize(
    "bar,covered,full,intraday,resumed,expected",
    [
        (True, True, False, False, False, "NORMAL"),
        (False, True, True, False, False, "HALTED"),
        (True, True, False, True, False, "INTRADAY_HALTED"),
        (True, True, False, True, True, "INTRADAY_HALTED"),
        (False, True, False, False, False, "UNKNOWN"),
        (True, False, False, False, False, "UNKNOWN"),
        (False, False, True, False, False, "UNKNOWN"),
        (False, True, False, True, False, "UNKNOWN"),
        (True, True, True, False, False, "UNKNOWN"),
        (False, True, True, False, True, "UNKNOWN"),
        (True, True, True, False, True, "UNKNOWN"),
        (True, True, True, True, False, "UNKNOWN"),
        (True, True, False, False, True, "NORMAL"),
        (False, True, False, False, True, "UNKNOWN"),
    ],
)
def test_four_states(bar, covered, full, intraday, resumed, expected):
    frame = pd.DataFrame(
        [[bar, covered, full, intraday, resumed]],
        columns=[
            "has_bar",
            "covered",
            "full_suspend",
            "intraday_suspend",
            "resumed",
        ],
    )
    assert resolve_trading_status(frame).tolist() == [expected]


def test_missing_and_empty_partition_are_different(tmp_raw_root):
    events, coverage = read_suspensions(tmp_raw_root, ("2024-01",), required=False)
    assert events.empty and coverage.empty
    with pytest.raises(ValueError, match="Missing suspension partition"):
        read_suspensions(tmp_raw_root, ("2024-01",), required=True)
    _partition(tmp_raw_root, [])
    events, coverage = read_suspensions(tmp_raw_root, ("2024-01",), required=True)
    assert events.empty and coverage.trading_day.tolist() == [DAY]


def test_legacy_and_tampered_partitions_rejected(tmp_raw_root):
    path = _partition(tmp_raw_root, [])
    path.with_suffix(".coverage.json").unlink()
    with pytest.raises(ValueError, match="Missing suspension coverage"):
        read_suspensions(tmp_raw_root, ("2024-01",), required=True)
    publish_coverage(path, [DAY])
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Invalid suspension coverage"):
        read_suspensions(tmp_raw_root, ("2024-01",), required=False)


def test_conflicting_event_timing_and_unknown_type_rejected():
    frame = pd.DataFrame(
        [
            ["600000.SH", "20240102", "S", "09:30-10:00"],
            ["600000.SH", "20240102", "S", None],
        ],
        columns=COLUMNS,
    )
    with pytest.raises(ValueError, match="conflicting"):
        normalize_events(frame)
    frame.loc[0, "suspend_type"] = "X"
    with pytest.raises(ValueError, match="event types"):
        normalize_events(frame)


def test_partial_month_coverage_does_not_mark_other_days_normal(tmp_raw_root):
    # 证据来自库内覆盖表（P2-2）：只覆盖了 DAY，其余日期不能推断为 NORMAL。
    market = pd.DataFrame(
        {"instrument_id": [1] * 3, "dt": [DAY, date(2024, 1, 3), date(2024, 2, 1)]}
    )
    importer = StockBars1dImporter(None, IngestContext(paths=tmp_raw_root))
    importer._status_evidence = lambda ids, days: (pd.DataFrame(), {DAY})
    assert importer._trading_status(market, []).tolist() == ["NORMAL", "UNKNOWN", "UNKNOWN"]


def test_events_outside_manifest_rejected(tmp_raw_root):
    _partition(tmp_raw_root, [["600000.SH", "20240103", "S", None]])
    with pytest.raises(ValueError, match="outside proven coverage"):
        read_suspensions(tmp_raw_root, ("2024-01",), required=True)


@pytest.mark.integration
def test_event_replay_empty_correction_and_missing_bar(pg_conn, tmp_raw_root):
    from gr_data.db.trading_status import load_stock_trading_status

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
    for day in [DAY, date(2024, 1, 3), date(2024, 1, 4)]:
        pg_conn.execute(
            "INSERT INTO meta.trading_calendar (exchange,trading_day,is_open) "
            "VALUES ('XSHG',%s,true)",
            (day,),
        )
    pg_conn.execute(
        "INSERT INTO market.stock_bar_1d "
        "(instrument_id,dt,trading_day,source,trading_status) "
        "VALUES (%s,'2024-01-03','2024-01-03','tushare','HALTED')",
        (iid,),
    )
    pg_conn.commit()
    ctx = IngestContext(paths=tmp_raw_root, months=("2024-01",))
    days = [DAY, date(2024, 1, 3), date(2024, 1, 4)]
    rows = [
        ["600000.SH", "20240102", "S", None],
        ["600000.SH", "20240103", "S", "09:30-10:00"],
        ["600000.SH", "20240103", "R", None],
    ]
    _partition(tmp_raw_root, rows, days=days)
    for _ in range(2):
        assert SuspensionImporter(pg_conn, ctx).run().rows_written == 3
    result = load_stock_trading_status(pg_conn, [iid], DAY, days[-1])
    assert result.trading_status.tolist() == ["HALTED", "INTRADAY_HALTED", "UNKNOWN"]
    assert pg_conn.execute("SELECT count(*) FROM market.stock_suspend_event").fetchone()[0] == 3
    assert pg_conn.execute("SELECT count(*) FROM market.stock_bar_1d").fetchone()[0] == 1
    assert (
        pg_conn.execute("SELECT trading_status FROM market.stock_bar_1d").fetchone()[0]
        == "INTRADAY_HALTED"
    )
    # 无证据不能删除旧事件，失败后事务没有残留修改。
    path = tmp_raw_root.dataset_file("tushare", "suspend_d", "2024-01")
    proof = path.with_suffix(".coverage.json")
    previous_bytes, previous_proof = path.read_bytes(), proof.read_bytes()
    proof.unlink()
    with pytest.raises(ValueError, match="coverage"):
        SuspensionImporter(pg_conn, ctx).run()
    assert pg_conn.execute("SELECT count(*) FROM market.stock_suspend_event").fetchone()[0] == 3
    # 新的合法空观察撤销旧事件，同时刷新已有 bar，不生成无价格占位行。
    _partition(tmp_raw_root, [], days=days)
    assert SuspensionImporter(pg_conn, ctx).run().rows_written == 0
    assert pg_conn.execute("SELECT count(*) FROM market.stock_suspend_event").fetchone()[0] == 0
    result = load_stock_trading_status(pg_conn, [iid], DAY, days[-1])
    assert result.trading_status.tolist() == ["UNKNOWN", "NORMAL", "UNKNOWN"]
    assert (
        pg_conn.execute("SELECT trading_status FROM market.stock_bar_1d").fetchone()[0] == "NORMAL"
    )
    # 旧观察不能撤回较新快照，且当前状态不能受失败影响。
    path.write_bytes(previous_bytes)
    proof.write_bytes(previous_proof)
    with pytest.raises(ValueError, match="Older suspension"):
        SuspensionImporter(pg_conn, ctx).run()
    assert pg_conn.execute("SELECT count(*) FROM market.stock_suspend_event").fetchone()[0] == 0
    with pytest.raises(ValueError, match="Incomplete trading calendar"):
        load_stock_trading_status(pg_conn, [iid], DAY, date(2024, 1, 5))
    with pytest.raises(ValueError, match="Unknown or non-stock"):
        load_stock_trading_status(pg_conn, [-1], DAY, DAY)
    from gr_data.common.ownership import OwnershipError, OwnershipManager

    OwnershipManager(pg_conn).claim("market.stock_suspend_event", "other", force=True)
    pg_conn.commit()
    with pytest.raises(OwnershipError):
        SuspensionImporter(pg_conn, ctx).run()


@pytest.mark.integration
def test_unmapped_events_rollback_ownership(pg_conn, tmp_raw_root):
    _partition(tmp_raw_root, [["600000.SH", "20240102", "S", None]])
    with pytest.raises(ValueError, match="Unmapped"):
        SuspensionImporter(pg_conn, IngestContext(paths=tmp_raw_root)).run()
    assert pg_conn.execute("SELECT count(*) FROM ops.table_ownership").fetchone()[0] == 0
    assert pg_conn.execute("SELECT count(*) FROM market.stock_suspend_coverage").fetchone()[0] == 0
