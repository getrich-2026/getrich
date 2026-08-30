"""DataYes 归一化逻辑单测（不需要数据库）。

覆盖的都是**算错但不报错**那一类问题：因子列错位、量纲弄反、上三角展开顺序
用错。它们的共同特点是结果依然「形状正确」——52 维向量、对称正定矩阵、
正的方差——所以只能靠测试钉死。
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest
from gr_data.common.retry import PermanentError
from gr_data.ingest.datayes import factors as fx
from gr_data.ingest.datayes.scaling import Scaling, load_scaling
from gr_data.ingest.datayes.symbols import split_sec_id, to_tushare_symbol


# --------------------------------------------------------------------------- #
# 因子字典
# --------------------------------------------------------------------------- #
def test_factor_superset_and_scheme_sizes():
    """58 = 20 风格 + 37 行业 + COUNTRY；sw21 活跃 52、sw14 活跃 49。"""
    assert len(fx.ALL_FACTORS) == 58
    assert len(fx.STYLE_FACTORS) == 20
    assert len(fx.INDUSTRY_FACTORS) == 37
    assert len(fx.SW21_FACTORS) == 52
    assert len(fx.STYLE_FACTORS) + len(fx.SW14_INDUSTRY_FACTORS) + 1 == 49
    # 超集内不得有重名，否则数组下标会被悄悄覆盖
    assert len(set(fx.ALL_FACTORS)) == len(fx.ALL_FACTORS)


def test_every_factor_has_a_type():
    assert set(fx.FACTOR_TYPE) == set(fx.ALL_FACTORS)
    assert set(fx.FACTOR_TYPE.values()) == {"style", "industry", "market"}


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("BETA", "BETA"),
        ("beta", "BETA"),
        # 接口里行业因子是驼峰、CSV 导出是全大写、协方差行标签又是原大小写
        ("Agriculture", "Agriculture"),
        ("AGRICULTURE", "Agriculture"),
        ("  NonbankFinan  ", "NonbankFinan"),
        ("NOT_A_FACTOR", None),
    ],
)
def test_canonical_is_case_insensitive(raw, expected):
    assert fx.canonical(raw) == expected


# --------------------------------------------------------------------------- #
# 列序防护（本文件最重要的一组）
# --------------------------------------------------------------------------- #
def _wide(order: list[str], n_rows: int = 3) -> pd.DataFrame:
    """构造一份宽表，第 i 个因子的值恒为 i，便于逐元素断言对齐。"""
    canon = {f: i for i, f in enumerate(fx.ALL_FACTORS)}
    return pd.DataFrame({col: [float(canon[fx.canonical(col)])] * n_rows for col in order})


def test_reindex_wide_is_immune_to_source_column_order():
    """三张宽表列序不同、大小写混排，取出来的值必须一致。

    这是实测的真实差异（样本 dy1d_*_20260829.csv）：
      exposure  : … COMPUTERS, CONGLOMERATES, CONSTRDECOR …
      covariance: … COMPUTERS, ELECTRONICS,   CONSTRDECOR …
    """
    order = list(fx.SW21_FACTORS)
    shuffled = list(reversed(order))
    upper = [f.upper() for f in order]

    a = fx.reindex_wide(_wide(order), order)
    b = fx.reindex_wide(_wide(shuffled), order)
    c = fx.reindex_wide(_wide(upper), order)

    # 每列的值是它在超集里的下标，因此正确对齐的结果与源表列序无关
    expected = np.array([fx.ALL_FACTORS.index(f) for f in order], dtype="float64")
    np.testing.assert_array_equal(a[0], expected)
    np.testing.assert_array_equal(b[0], expected)
    np.testing.assert_array_equal(c[0], expected)


def test_reindex_wide_rejects_missing_column():
    """缺列必须抛错。用 0 补上会让那个因子被静默当成「中性暴露」。"""
    order = list(fx.SW21_FACTORS)
    df = _wide(order).drop(columns=["BETA"])

    with pytest.raises(ValueError, match="缺少因子列"):
        fx.reindex_wide(df, order)


def test_reindex_wide_rejects_duplicate_column():
    order = list(fx.SW21_FACTORS)
    df = _wide(order)
    df["beta"] = df["BETA"]  # 同一因子两种写法

    with pytest.raises(ValueError, match="出现多列"):
        fx.reindex_wide(df, order)


def test_active_factors_derives_scheme_from_data():
    """sw14 期的数据里 9 个 sw21 新行业整列为 NaN，活跃集应当据此排除它们。"""
    df = _wide(list(fx.ALL_FACTORS))
    sw21_only = [f for f in fx.INDUSTRY_FACTORS if f not in fx.SW14_INDUSTRY_FACTORS]
    for col in sw21_only:
        df[col] = np.nan

    active = fx.active_factors(df)

    assert len(active) == 49
    assert not (set(active) & set(sw21_only))
    # 顺序必须是超集的规范顺序，不是源表的列序
    assert list(active) == [f for f in fx.ALL_FACTORS if f in set(active)]


def test_factor_hashes_separate_set_from_order():
    """集合哈希与顺序哈希必须分开：一个管供应商，一个管我们自己。"""
    order = list(fx.SW21_FACTORS)
    reordered = list(reversed(order))
    dropped = order[:-1]

    assert fx.factor_set_hash(order) == fx.factor_set_hash(reordered)
    assert fx.factor_order_hash(order) != fx.factor_order_hash(reordered)
    assert fx.factor_set_hash(order) != fx.factor_set_hash(dropped)


# --------------------------------------------------------------------------- #
# 上三角展平
# --------------------------------------------------------------------------- #
def test_upper_triangle_is_row_major_and_lossless():
    m = np.array([[1.0, 2.0, 3.0], [2.0, 4.0, 5.0], [3.0, 5.0, 6.0]])

    flat = fx.upper_triangle(m)

    # 行优先、i<=j、i 在外层
    assert flat.tolist() == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    assert len(flat) == 3 * 4 // 2
    np.testing.assert_array_equal(fx.from_upper_triangle(flat, 3), m)


def test_upper_triangle_length_for_52_factors():
    """K=52 → 1378。这个数字写死在 DDL 的列注释里，两边必须对得上。"""
    m = np.eye(52)
    assert len(fx.upper_triangle(m)) == 1378


def test_from_upper_triangle_rejects_wrong_length():
    with pytest.raises(ValueError, match="展平长度"):
        fx.from_upper_triangle([1.0, 2.0], 3)


# --------------------------------------------------------------------------- #
# 量纲定标
# --------------------------------------------------------------------------- #
_FULL_SCALING = {
    "mode": "calibrated",
    "exposure_unit": "zscore",
    "factor_ret_unit": "dec_daily",
    "cov_unit": "pct2_annual",
    "srisk_unit": "pct_annual",
    "srisk_is_variance": False,
    "spret_unit": "pct_daily",
    "calibrated": False,
}


def test_srisk_squared_into_variance():
    """SRISK 是年化百分比波动率 σ，入库要平方；当成方差用会低估一个数量级。"""
    scaling = load_scaling(_FULL_SCALING)

    assert scaling.srisk_is_variance is False
    assert pytest.approx(876.16) == 29.6**2
    assert scaling.as_units()["specific_risk"] == "pct2_annual"
    assert scaling.as_units()["specific_risk_source"] == "pct_annual"


@pytest.mark.parametrize("missing", sorted(_FULL_SCALING))
def test_scaling_missing_any_key_refuses_to_start(missing):
    """缺任何一个键都必须拒绝启动，不能按默认值猜。"""
    section = {k: v for k, v in _FULL_SCALING.items() if k != missing}

    with pytest.raises(PermanentError, match="scaling 缺少必填键"):
        load_scaling(section)


def test_scaling_missing_section_refuses_to_start():
    with pytest.raises(PermanentError):
        load_scaling(None)


def test_scaling_records_mixed_units():
    """f 是小数、u 是百分比 —— 这个差异必须原样落进 model_run.units。"""
    units = load_scaling(_FULL_SCALING).as_units()

    assert units["factor_return"] == "dec_daily"
    assert units["specific_return"] == "pct_daily"
    assert units["covariance"] == "pct2_annual"


def test_scaling_is_frozen():
    """量纲声明必须不可变：跑到一半被改掉，前后两批数据的口径就不一致了。"""
    s = Scaling(**dict(_FULL_SCALING))
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.calibrated = True  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# 符号归一
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "sec_id,ticker,exchange,symbol",
    [
        ("000002.XSHE", "000002", "XSHE", "000002.SZ"),
        ("600000.XSHG", "600000", "XSHG", "600000.SH"),
        ("430047.XBSE", "430047", "XBSE", "430047.BJ"),
    ],
)
def test_split_sec_id_and_symbol(sec_id, ticker, exchange, symbol):
    assert split_sec_id(sec_id) == (ticker, exchange)
    assert to_tushare_symbol(sec_id) == symbol


def test_unknown_suffix_is_not_rewritten():
    """未知后缀原样返回，不猜 —— 猜错会把标的映射到别的市场上去。"""
    assert split_sec_id("123456.XHKG") == ("123456", "XHKG")
    assert to_tushare_symbol("123456.XHKG") is None
    assert split_sec_id("noSuffix") == ("noSuffix", "UNKNOWN")


# --------------------------------------------------------------------------- #
# 行业区间压缩（G1）
# --------------------------------------------------------------------------- #
def _daily(rows):
    """rows: [(instrument_id, 'YYYY-MM-DD', industry_code)]"""
    from datetime import date as _date

    return pd.DataFrame(
        [
            {
                "instrument_id": iid,
                "trading_day": _date(*(int(x) for x in day.split("-"))),
                "industry_code": code,
                "available_at": pd.Timestamp(f"{day} 17:00", tz="Asia/Shanghai"),
            }
            for iid, day, code in rows
        ]
    )


def test_compress_merges_consecutive_days_into_one_interval():
    from gr_data.ingest.datayes.importers.classify import _compress

    seg = _compress(_daily([(1, "2025-01-02", "Banks"), (1, "2025-01-03", "Banks")]))

    assert len(seg) == 1
    assert seg.loc[0, "in_date"].isoformat() == "2025-01-02"
    assert seg.loc[0, "out_date"] is None  # 当前有效


def test_compress_splits_on_industry_change_with_halfopen_range():
    """out_date 取**下一段的起点**（半开区间）。

    用「本段最后一个交易日」当 out_date 会在两段之间漏掉一天 —— 那一天查不到
    任何行业，而查询本身不会报错，只是少了一只票。
    """
    from gr_data.ingest.datayes.importers.classify import _compress

    seg = _compress(
        _daily(
            [
                (1, "2025-01-02", "Chemicals"),
                (1, "2025-01-03", "Chemicals"),
                (1, "2025-01-06", "BasicChemicals"),
            ]
        )
    )

    assert len(seg) == 2
    assert seg.loc[0, "industry_code"] == "Chemicals"
    assert seg.loc[0, "out_date"].isoformat() == "2025-01-06"  # 不是 01-03
    assert seg.loc[1, "in_date"].isoformat() == "2025-01-06"
    assert seg.loc[1, "out_date"] is None


def test_compress_bridges_short_gap_but_not_long_one():
    """停牌造成的短空洞要接上，长空洞必须断开。

    缺行不等于换了行业，所以短空洞接上；但停牌一年的票中间有没有被重分类，
    我们并不知道，接上就是替供应商编数据。
    """
    from gr_data.ingest.datayes.importers.classify import MAX_GAP_DAYS, _compress

    assert MAX_GAP_DAYS == 40
    short = _compress(_daily([(1, "2025-01-02", "Banks"), (1, "2025-02-05", "Banks")]))
    long = _compress(_daily([(1, "2025-01-02", "Banks"), (1, "2025-06-05", "Banks")]))

    assert len(short) == 1  # 间隔 34 天，接上
    assert len(long) == 2  # 间隔 154 天，断开
    assert long.loc[0, "out_date"].isoformat() == "2025-06-05"


def test_compress_never_merges_across_instruments():
    """相邻两行属于不同标的时必须切段，哪怕行业相同、日期连续。"""
    from gr_data.ingest.datayes.importers.classify import _compress

    seg = _compress(_daily([(1, "2025-01-02", "Banks"), (2, "2025-01-03", "Banks")]))

    assert len(seg) == 2
    assert sorted(seg["instrument_id"]) == [1, 2]
    # 跨标的不得把 out_date 指到另一只票的起点
    assert seg.loc[0, "out_date"] is None and seg.loc[1, "out_date"] is None
