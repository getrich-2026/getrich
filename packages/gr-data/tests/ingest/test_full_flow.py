"""全流程集成测试（需要 docker PostgreSQL）。

每个 provider 走：raw 抓取(Fake) → parquet → ingest → PG，校验：
- meta.instruments / symbol_map / trading_calendar 行数
- market.*_bar_1d 行数与来源
- ops.table_ownership 归属登记
并验证归属冲突：另一 provider 不能写同一张表（除非 force）。
"""

from __future__ import annotations

import pytest
from gr_data.common.ownership import OwnershipError, OwnershipManager
from gr_data.ingest.base import IngestContext
from gr_data.raw.base import RawContext


pytestmark = pytest.mark.integration


def _raw_ctx(paths):
    return RawContext(
        paths=paths,
        rate_limit={"sleep_between_requests_sec": 0, "max_retries": 1, "retry_backoff_base_sec": 0},
    )


def _count(conn, table):
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table}")
        return cur.fetchone()[0]


def _run_yinhe_raw(paths, fake_yinhe):
    from gr_data.raw.yinhe import REGISTRY

    ctx = _raw_ctx(paths)
    for name in ("calendar", "hist_code_list", "kline_day"):
        REGISTRY[name](fake_yinhe, ctx).fetch("init")


def test_yinhe_full_flow(pg_conn, tmp_raw_root, fake_yinhe):
    _run_yinhe_raw(tmp_raw_root, fake_yinhe)
    ctx = IngestContext(paths=tmp_raw_root)

    from gr_data.ingest.yinhe import REGISTRY

    # 顺序入库：instruments -> symbol_map -> calendar -> bars
    for name in (
        "instruments",
        "symbol_map",
        "calendar",
        "stock_bar_1d",
        "etf_bar_1d",
        "index_bar_1d",
    ):
        REGISTRY[name](pg_conn, ctx).run()

    assert _count(pg_conn, "meta.instruments") == 4  # 2 stock + 1 etf + 1 index
    assert _count(pg_conn, "meta.symbol_map") == 4
    assert _count(pg_conn, "meta.trading_calendar") == 6  # 3 days x 2 exch
    assert _count(pg_conn, "market.stock_bar_1d") == 4  # 2 codes x 2 days
    assert _count(pg_conn, "market.etf_bar_1d") == 2

    # 归属登记
    owners = {o.target: o.provider for o in OwnershipManager(pg_conn).list_all()}
    assert owners["market.stock_bar_1d"] == "yinhe"
    assert owners["meta.instruments"] == "yinhe"

    # source 列正确
    with pg_conn.cursor() as cur:
        cur.execute("SELECT DISTINCT source FROM market.stock_bar_1d")
        assert [r[0] for r in cur.fetchall()] == ["yinhe"]


def test_ownership_conflict(pg_conn, tmp_raw_root, fake_yinhe, fake_ricequant):
    # yinhe 先占 stock_bar_1d
    _run_yinhe_raw(tmp_raw_root, fake_yinhe)
    ctx = IngestContext(paths=tmp_raw_root)
    from gr_data.ingest.yinhe import REGISTRY as YREG

    for name in ("instruments", "symbol_map", "stock_bar_1d"):
        YREG[name](pg_conn, ctx).run()

    # ricequant 试图写同一张表 -> 冲突
    from gr_data.raw.ricequant import REGISTRY as RQ_RAW

    rctx = _raw_ctx(tmp_raw_root)
    RQ_RAW["instruments"](fake_ricequant, rctx).fetch("init")
    RQ_RAW["bars_1d"](fake_ricequant, rctx).fetch("init")

    from gr_data.ingest.ricequant import REGISTRY as RREG

    with pytest.raises(OwnershipError):
        RREG["stock_bar_1d"](pg_conn, ctx).run()

    # force_ownership=True 可转移
    pg_conn.rollback()
    forced = IngestContext(paths=tmp_raw_root, force_ownership=True)
    # 需要 ricequant 自己的 instruments/symbol_map 才能解析 id
    RREG["instruments"](pg_conn, forced).run()
    RREG["symbol_map"](pg_conn, forced).run()
    RREG["stock_bar_1d"](pg_conn, forced).run()
    owner = OwnershipManager(pg_conn).owner("market.stock_bar_1d")
    assert owner.provider == "ricequant"


def test_ricequant_and_insight_flow(pg_conn, tmp_raw_root, fake_ricequant, fake_insight):
    # ricequant
    from gr_data.raw.ricequant import REGISTRY as RQ_RAW

    rctx = _raw_ctx(tmp_raw_root)
    for name in ("instruments", "calendar", "bars_1d"):
        RQ_RAW[name](fake_ricequant, rctx).fetch("init")

    ctx = IngestContext(paths=tmp_raw_root)
    from gr_data.ingest.ricequant import REGISTRY as RREG

    for name in ("instruments", "symbol_map", "calendar", "stock_bar_1d"):
        RREG[name](pg_conn, ctx).run()
    assert _count(pg_conn, "market.stock_bar_1d") == 4
    assert OwnershipManager(pg_conn).owner("market.stock_bar_1d").provider == "ricequant"

    # insight 写 index_bar_1d（与 ricequant 不冲突的表）
    from gr_data.raw.insight import REGISTRY as IN_RAW

    ictx = _raw_ctx(tmp_raw_root)
    for name in ("basic_info", "trading_days", "kline_day"):
        IN_RAW[name](fake_insight, ictx).fetch("init")

    from gr_data.ingest.insight import REGISTRY as IREG

    # insight 的 instruments/symbol_map 会与 ricequant 抢 meta.instruments，用 force 演示转移
    fctx = IngestContext(paths=tmp_raw_root, force_ownership=True)
    IREG["instruments"](pg_conn, fctx).run()
    IREG["symbol_map"](pg_conn, fctx).run()
    IREG["index_bar_1d"](pg_conn, fctx).run()
    assert _count(pg_conn, "market.index_bar_1d") == 2


def _run_tushare_raw(paths, fake_tushare):
    from gr_data.raw.tushare import REGISTRY

    ctx = _raw_ctx(paths)
    ctx.start_date = 20240101
    for name in (
        "instruments",
        "calendar",
        "daily",
        "daily_basic",
        "adj_factor",
        "stk_limit",
        "suspend_d",
        "index_daily",
        "fut_daily",
    ):
        REGISTRY[name](fake_tushare, ctx).fetch("init")


def test_tushare_full_flow(pg_conn, tmp_raw_root, fake_tushare):
    _run_tushare_raw(tmp_raw_root, fake_tushare)
    ctx = IngestContext(paths=tmp_raw_root)

    from gr_data.ingest.tushare import GROUPS, REGISTRY

    for name in GROUPS["all"]:
        REGISTRY[name](pg_conn, ctx).run()

    # 2 stock + 1 index + 1 future
    assert _count(pg_conn, "meta.instruments") == 4
    assert _count(pg_conn, "meta.symbol_map") == 4
    assert _count(pg_conn, "meta.trading_calendar") == 6  # 3 cal_date x 2 exch
    assert _count(pg_conn, "market.stock_bar_1d") == 4  # 2 codes x 2 days
    assert _count(pg_conn, "market.index_bar_1d") == 2
    assert _count(pg_conn, "market.future_bar_1d") == 2

    with pg_conn.cursor() as cur:
        # 单位换算落库正确：vol 1000 手 → 100000 股；amount 10500 千元 → 10500000 元
        cur.execute(
            "SELECT volume, amount, adj_factor, limit_up, trading_status, source "
            "FROM market.stock_bar_1d b JOIN meta.instruments i USING (instrument_id) "
            "WHERE i.symbol = '600000.SH' AND b.dt = DATE '2024-01-02'"
        )
        volume, amount, adj, limit_up, status, source = cur.fetchone()
        assert float(volume) == 1000.0 * 100
        assert float(amount) == 10500.0 * 1000
        assert float(adj) == 1.25
        assert float(limit_up) == 10.78
        assert status == "HALTED"  # Fake 让 600000.SH 首日停牌
        assert source == "tushare"

        # 期货：amount 万元 → 元；vol/oi 保持手
        cur.execute(
            "SELECT volume, amount, open_interest, settle FROM market.future_bar_1d LIMIT 1"
        )
        volume, amount, oi, settle = cur.fetchone()
        assert float(volume) == 5000.0
        assert float(amount) == 34250.0 * 10000
        assert float(oi) == 12000.0
        assert float(settle) == 68400.0

        # 交易日历：next_trading_day 由 is_open 推导，非交易日不作为后继
        cur.execute(
            "SELECT next_trading_day FROM meta.trading_calendar "
            "WHERE exchange = 'XSHG' AND trading_day = DATE '2024-01-02'"
        )
        assert cur.fetchone()[0].isoformat() == "2024-01-03"

        # 代码归一化：交易所后缀映射为 canonical
        cur.execute("SELECT exchange FROM meta.instruments WHERE symbol = 'CU2401.SHF'")
        assert cur.fetchone()[0] == "SHFE"
        cur.execute("SELECT exchange FROM meta.instruments WHERE symbol = '000001.SZ'")
        assert cur.fetchone()[0] == "XSHE"

    owners = {o.target: o.provider for o in OwnershipManager(pg_conn).list_all()}
    assert owners["market.stock_bar_1d"] == "tushare"
    assert owners["market.future_bar_1d"] == "tushare"
    assert owners["market.stock_daily_basic"] == "tushare"
    assert owners["market.adj_factor_ts"] == "tushare"


def test_daily_basic_jsonb_roundtrip(pg_conn, tmp_raw_root, fake_tushare):
    """JSONB 列的 COPY 通路必须真的走通一次。

    `upsert_rows` 走的是文本 COPY，psycopg 靠首行的 Python 类型推断适配器；
    dict → jsonb 能不能落地、`set_types` 有没有生效，只有真库能证明。
    mock 测试在这件事上是完全无效的。
    """
    _run_tushare_raw(tmp_raw_root, fake_tushare)
    ctx = IngestContext(paths=tmp_raw_root)

    from gr_data.ingest.tushare import REGISTRY

    for name in ("instruments", "symbol_map", "daily_basic", "adj_factor_ts"):
        REGISTRY[name](pg_conn, ctx).run()

    assert _count(pg_conn, "market.stock_daily_basic") == 4  # 2 codes x 2 days
    assert _count(pg_conn, "market.adj_factor_ts") == 4

    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT total_market_cap, float_market_cap, close, turnover_rate, "
            "       raw_payload->>'pb', raw_payload->>'total_share', raw_payload ? 'close' "
            "FROM market.stock_daily_basic b JOIN meta.instruments i USING (instrument_id) "
            "WHERE i.symbol = '600000.SH' AND b.trading_day = DATE '2024-01-02'"
        )
        total_mv, circ_mv, close, turnover, pb, total_share, has_close = cur.fetchone()
        # 万元 → 元
        assert float(total_mv) == 120_000_000.0
        assert float(circ_mv) == 80_000_000.0
        assert float(close) == 10.5
        assert float(turnover) == 1.25
        # raw_payload 是真 jsonb（能用 ->> 取值），且不重复装已提升的列
        assert float(pb) == 1.2
        assert float(total_share) == 100000.0  # 原值原名，不换算
        assert has_close is False

        cur.execute(
            "SELECT adj_factor, source FROM market.adj_factor_ts a "
            "JOIN meta.instruments i USING (instrument_id) "
            "WHERE i.symbol = '600000.SH' AND a.trading_day = DATE '2024-01-02'"
        )
        adj, source = cur.fetchone()
        assert float(adj) == 1.25
        assert source == "tushare"
