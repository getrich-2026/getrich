"""全流程集成测试（需要 docker PostgreSQL）。

每个 provider 走：raw 抓取(Fake) → parquet → ingest → PG，校验：
- meta.instruments / symbol_map / trading_calendar 行数
- market.*_bar_1d 行数与来源
- ops.table_ownership 归属登记
并验证归属冲突：另一 provider 不能写同一张表（除非 force）。
"""

from __future__ import annotations

from datetime import date, datetime

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

    for name in ("instruments", "symbol_map", "daily_basic", "adj_factor_ts", "valuation_1d"):
        REGISTRY[name](pg_conn, ctx).run()

    assert _count(pg_conn, "market.stock_daily_basic") == 4  # 2 codes x 2 days
    assert _count(pg_conn, "market.adj_factor_ts") == 4
    assert _count(pg_conn, "fundamental.valuation_1d") == 4

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

        # fundamental.valuation_1d：同一份 raw 的另一条路，单位已归一。
        # available_at 断言的是**瞬间**而不是 utcoffset —— 后者只反映读取连接的
        # 会话时区，换个连接就变，证明不了写入时钉对了时区。
        cur.execute(
            "SELECT total_mv, circ_mv, pb, pe_ttm, currency, "
            "       available_at AT TIME ZONE 'UTC' "
            "FROM fundamental.valuation_1d v "
            "JOIN meta.instruments i USING (instrument_id) "
            "WHERE i.symbol = '600000.SH' AND v.trading_day = DATE '2024-01-02'"
        )
        total_mv, circ_mv, pb, pe_ttm, currency, avail_utc = cur.fetchone()
        assert float(total_mv) == 120_000_000.0
        assert float(circ_mv) == 80_000_000.0
        assert float(pb) == 1.2
        assert float(pe_ttm) == 11.5
        assert currency == "CNY"
        assert avail_utc == datetime(2024, 1, 2, 9, 0)  # 17:00 +08:00


_SCALING = {
    "mode": "calibrated",
    "exposure_unit": "zscore",
    "factor_ret_unit": "dec_daily",
    "cov_unit": "pct2_annual",
    "srisk_unit": "pct_annual",
    "srisk_is_variance": False,
    "spret_unit": "pct_daily",
    "calibrated": False,
}


def test_datayes_full_flow(pg_conn, tmp_raw_root, fake_tushare, fake_datayes):
    """raw(Fake) → parquet → ingest → PG，重点验证真库才能证明的那几件事：

    - `REAL[]` / `DOUBLE PRECISION[]` / `JSONB` 三种列的 COPY 通路真的能走通；
    - 数组长度约束（exposure=K、cov_flat=K(K+1)/2）真的生效；
    - 因子值按 `model_run.factor_order` 对齐，而不是按源表列序。
    """
    from gr_data.ingest.datayes import REGISTRY as DY_REGISTRY
    from gr_data.ingest.datayes.factors import ALL_FACTORS, SW21_FACTORS, SW21_INDUSTRY_FACTORS

    # Fake 让每行的第一个行业哑变量为 1，其余为 0
    fx_first_industry = SW21_INDUSTRY_FACTORS[0]
    from gr_data.ingest.datayes.scaling import load_scaling
    from gr_data.ingest.tushare import REGISTRY as TS_REGISTRY
    from gr_data.raw.datayes import REGISTRY as DY_RAW

    # datayes 的 symbol_map 要靠 tushare 先把 meta.instruments 建好
    _run_tushare_raw(tmp_raw_root, fake_tushare)
    ctx = IngestContext(paths=tmp_raw_root)
    for name in ("instruments", "symbol_map"):
        TS_REGISTRY[name](pg_conn, ctx).run()

    raw_ctx = _raw_ctx(tmp_raw_root)
    raw_ctx.start_date = 20240101
    for ds in DY_RAW:
        DY_RAW[ds](fake_datayes, raw_ctx).fetch("init")

    scaling = load_scaling(_SCALING)
    from gr_data.ingest.datayes import GROUPS as DY_GROUPS

    for name in DY_GROUPS["all"]:
        DY_REGISTRY[name](pg_conn, ctx, scaling=scaling).run()

    k = len(SW21_FACTORS)
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT run_id, factor_count, array_length(factor_order, 1), calibrated, "
            "       annualization_basis, units->>'factor_return', units->>'specific_return' "
            "FROM factor.model_run"
        )
        run_id, count, order_len, calibrated, basis, f_unit, u_unit = cur.fetchone()
        assert count == k and order_len == k
        # 全区间复核前必须是 false，下游据此把指标标成 degraded
        assert calibrated is False
        assert basis == "annual_252"
        # f 是小数、u 是百分比 —— 混用会差 100 倍，口径必须落库
        assert f_unit == "dec_daily"
        assert u_unit == "pct_daily"

        cur.execute("SELECT count(*) FROM factor.definition")
        assert cur.fetchone()[0] == k

        # 数组长度：DDL 的 CHECK 已经把关，这里再断言一次实际落库值
        cur.execute(
            "SELECT count(*) FROM factor.exposure WHERE array_length(exposure, 1) <> %s", (k,)
        )
        assert cur.fetchone()[0] == 0
        cur.execute(
            "SELECT count(*) FROM factor.covariance WHERE array_length(cov_flat, 1) <> %s",
            (k * (k + 1) // 2,),
        )
        assert cur.fetchone()[0] == 0

        # 因子值按 factor_order 对齐：Fake 让每个因子的值等于它在超集里的下标，
        # 而三张宽表的源列序互不相同 —— 按源列序取值这条断言必挂。
        cur.execute(
            "SELECT factor_order, ret_vector FROM factor.model_run, factor.factor_return LIMIT 1"
        )
        factor_order, ret_vector = cur.fetchone()
        for i, name in enumerate(factor_order):
            assert ret_vector[i] == pytest.approx(ALL_FACTORS.index(name)), f"{name} 错位"

        # SRISK 29.6（年化百分比波动率 σ）→ specific_var = σ² = 876.16
        cur.execute("SELECT specific_var FROM factor.specific_risk LIMIT 1")
        assert cur.fetchone()[0] == pytest.approx(876.16, rel=1e-4)
        # SPRET 是百分比，原样入库不缩放
        cur.execute("SELECT specific_ret FROM factor.specific_return LIMIT 1")
        assert cur.fetchone()[0] == pytest.approx(1.5)

        # available_at 取供应商 updateTime，并按 Asia/Shanghai 解释。
        # 断言的是**时刻**而不是 utcoffset —— 后者只反映读取连接的会话时区，
        # 换个连接就变，测不出「入库时是否钉了时区」。Fake 给的 17:00（东八）
        # 必须落成 UTC 09:00；若入库时漏了 tz_localize，CI 的 UTC 机器上会存成 17:00Z。
        cur.execute(
            "SELECT min(available_at AT TIME ZONE 'UTC') FROM factor.exposure "
            "WHERE trading_day = DATE '2024-01-02'"
        )
        assert cur.fetchone()[0] == datetime(2024, 1, 2, 9, 0)

        # secID 与 meta.instruments.symbol 不是同一串，靠 symbol_map 对齐
        cur.execute("SELECT source_symbol FROM meta.symbol_map WHERE source = 'datayes' ORDER BY 1")
        assert [r[0] for r in cur.fetchall()] == ["000001.XSHE", "600000.XSHG"]

        # classify（G1）：31 个一级节点，逐日归属压成区间。
        # Fake 让每行的第一个行业为 1、两天不变，因此每个标的只应得到一段，
        # 且 out_date 为 NULL（当前有效）——压成两段说明变化点判断错了。
        cur.execute("SELECT max_level, available_level FROM classify.scheme")
        assert cur.fetchone() == (3, 1)
        cur.execute("SELECT count(*) FROM classify.industry_node WHERE scheme_code = 'sw2021'")
        assert cur.fetchone()[0] == 31
        cur.execute(
            "SELECT industry_code, in_date, out_date, level "
            "FROM classify.instrument_industry ORDER BY instrument_id"
        )
        rows = cur.fetchall()
        assert len(rows) == 2
        for code, in_date, out_date, level in rows:
            assert code == fx_first_industry
            assert in_date == date(2024, 1, 2)
            assert out_date is None
            assert level == 1
        # external_code 恒 NULL：没有通联英文标识到申万官方码的权威映射，
        # 填一份猜的会让下游误以为能直接对接申万发布的成分数据。
        cur.execute("SELECT count(*) FROM classify.industry_node WHERE external_code IS NOT NULL")
        assert cur.fetchone()[0] == 0

    owners = {o.target: o.provider for o in OwnershipManager(pg_conn).list_all()}
    for table in ("factor.exposure", "factor.covariance", "factor.specific_risk"):
        assert owners[table] == "datayes"


def test_datayes_scaling_missing_config_refuses_to_start(pg_conn, tmp_raw_root):
    """量纲配置缺键时必须拒绝启动，而不是按默认系数算。"""
    from gr_data.common.retry import PermanentError
    from gr_data.ingest.datayes.scaling import load_scaling

    with pytest.raises(PermanentError, match="scaling 缺少必填键"):
        load_scaling({k: v for k, v in _SCALING.items() if k != "srisk_is_variance"})
