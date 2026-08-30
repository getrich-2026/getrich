"""CNE6-SW21 的因子字典，以及**唯一允许把宽表变成数组的函数**。

## 这个模块存在的理由

通联的三张宽表（exposure / covariance / factor_return）字段集合相同，
但**列顺序互不相同**，而且大小写还不统一。实测样本（2026-08-29 导出）：

    exposure  : … COMPUTERS, CONGLOMERATES, CONSTRDECOR, DEFENSE, ELECTRICALEQUIP, ELECTRONICS …
    covariance: … COMPUTERS, ELECTRONICS,   CONSTRDECOR, DEFENSE, ELECTRICALEQUIP, NONBANKFINAN …

JSON 接口里风格因子是全大写（`BETA`），行业因子是驼峰（`Agriculture`、
`BuildMater`），而 CSV 导出全是大写。协方差的行标签 `factorName` 用的又是
原大小写。

按各表自己的列序 `.to_numpy()` 展平 → 因子错位 → **数值全错，但没有任何报错**：
错位后的协方差矩阵依然对称、依然正定，暴露向量依然是 52 维。这是本次接入里
唯一一处「算错而不报错」的地方，所以取值必须**只经由 `reindex_wide`**，
禁止任何地方写 `df[factor_cols].to_numpy()`。

## 因子集合随体系切换而变

超集是 58 个（20 风格 + 37 行业 + COUNTRY），但同一天只有一部分有值：
申万 2014 体系下 49 个（9 个 sw21 新行业整列为 NaN），申万 2021 体系下 52 个
（6 个 sw14 专有行业整列为 NaN）。分界日约在 2021-12-22。

因此**活跃因子集合从数据里派生，不写死**；写死的只有超集与它的顺序。
派生出来的集合与顺序存进 `factor.model_run.factor_order`，之后每天用
`factor_set_hash` 复核 —— 集合变了说明供应商换了体系，必须人工确认后开新
`model_version`，而不是让程序自己适应。
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import numpy as np
import pandas as pd


#: 20 个风格因子，顺序取自接口文档 `getDy1dExposureCNE6SW21_api.md` 的输出参数表。
STYLE_FACTORS: tuple[str, ...] = (
    "BETA",
    "MOMENTUM",
    "SIZE",
    "EARNYILD",
    "RESVOL",
    "GROWTH",
    "BTOP",
    "LEVERAGE",
    "LIQUIDTY",
    "MIDCAP",
    "DIVYILD",
    "EARNQLTY",
    "EARNVAR",
    "INVSQLTY",
    "LTREVRSL",
    "PROFIT",
    "ANALSENTI",
    "INDMOM",
    "SEASON",
    "STREVRSL",
)

#: 37 个行业因子。第二个元素是接口文档给出的体系标注：
#: "both" = sw14 与 sw21 都有，"sw14" / "sw21" = 仅该体系有。
#: `Conglomerates`（综合）在文档里没有标注，但实测 2020-12-31（sw14 期）有值，
#: 且 sw21 期的活跃行业数为 31 = 21(both) + 9(sw21) + 它，故归为 both。
_INDUSTRIES: tuple[tuple[str, str], ...] = (
    ("Agriculture", "both"),
    ("Automobiles", "both"),
    ("Banks", "both"),
    ("BuildMater", "both"),
    ("Chemicals", "sw14"),
    ("Commerce", "sw14"),
    ("Computers", "both"),
    ("Conglomerates", "both"),
    ("ConstrDecor", "both"),
    ("Defense", "both"),
    ("ElectricalEquip", "sw14"),
    ("Electronics", "both"),
    ("FoodBeverages", "both"),
    ("HealthCare", "both"),
    ("HomeAppliances", "both"),
    ("Leisure", "sw14"),
    ("LightIndustry", "both"),
    ("MachineEquip", "both"),
    ("Media", "both"),
    ("Mining", "sw14"),
    ("NonbankFinan", "both"),
    ("NonferrousMetals", "both"),
    ("RealEstate", "both"),
    ("Steel", "both"),
    ("Telecoms", "both"),
    ("TextileGarment", "sw14"),
    ("Transportation", "both"),
    ("Utilities", "both"),
    ("BasicChemicals", "sw21"),
    ("BeautyCare", "sw21"),
    ("Coal", "sw21"),
    ("EnvironProtect", "sw21"),
    ("Petroleum", "sw21"),
    ("PowerEquip", "sw21"),
    ("RetailTrade", "sw21"),
    ("SocialServices", "sw21"),
    ("TextileApparel", "sw21"),
)

#: 行业因子的中文名，用于 classify.industry_node。取自接口文档的字段说明。
INDUSTRY_NAMES: dict[str, str] = {
    "Agriculture": "农林牧渔",
    "Automobiles": "汽车",
    "Banks": "银行",
    "BuildMater": "建筑材料",
    "Chemicals": "化工",
    "Commerce": "商业贸易",
    "Computers": "计算机",
    "Conglomerates": "综合",
    "ConstrDecor": "建筑装饰",
    "Defense": "国防军工",
    "ElectricalEquip": "电气设备",
    "Electronics": "电子",
    "FoodBeverages": "食品饮料",
    "HealthCare": "医药生物",
    "HomeAppliances": "家用电器",
    "Leisure": "休闲服务",
    "LightIndustry": "轻工制造",
    "MachineEquip": "机械设备",
    "Media": "传媒",
    "Mining": "采掘",
    "NonbankFinan": "非银金融",
    "NonferrousMetals": "有色金属",
    "RealEstate": "房地产",
    "Steel": "钢铁",
    "Telecoms": "通信",
    "TextileGarment": "纺织服装",
    "Transportation": "交通运输",
    "Utilities": "公用事业",
    "BasicChemicals": "基础化工",
    "BeautyCare": "美容护理",
    "Coal": "煤炭",
    "EnvironProtect": "环保",
    "Petroleum": "石油石化",
    "PowerEquip": "电力设备",
    "RetailTrade": "商贸零售",
    "SocialServices": "社会服务",
    "TextileApparel": "纺织服饰",
}

INDUSTRY_FACTORS: tuple[str, ...] = tuple(name for name, _ in _INDUSTRIES)
SW21_INDUSTRY_FACTORS: tuple[str, ...] = tuple(
    name for name, scheme in _INDUSTRIES if scheme in ("both", "sw21")
)
SW14_INDUSTRY_FACTORS: tuple[str, ...] = tuple(
    name for name, scheme in _INDUSTRIES if scheme in ("both", "sw14")
)

MARKET_FACTOR = "COUNTRY"

#: 58 个因子的**超集与规范顺序**。派生出的任何活跃集合都按这个顺序排列，
#: 因此 exposure / covariance / factor_return 三张表落库后的下标一定对齐。
ALL_FACTORS: tuple[str, ...] = STYLE_FACTORS + INDUSTRY_FACTORS + (MARKET_FACTOR,)

#: 申万 2021 体系下的预期活跃集合（20 + 31 + 1）。**只用于断言，不用于取数** ——
#: 取数一律走 `active_factors()` 从当日数据派生。
SW21_FACTORS: tuple[str, ...] = STYLE_FACTORS + SW21_INDUSTRY_FACTORS + (MARKET_FACTOR,)

FACTOR_TYPE: dict[str, str] = {
    **{f: "style" for f in STYLE_FACTORS},
    **{f: "industry" for f in INDUSTRY_FACTORS},
    MARKET_FACTOR: "market",
}

_CANON: dict[str, str] = {f.upper(): f for f in ALL_FACTORS}


class FactorSetChangedError(RuntimeError):
    """当日的活跃因子集合与 model_run 记录的不一致。

    集合变了意味着供应商换了行业体系（如 sw14 → sw21）或增删了风格因子。
    此时**必须中断**：继续入库会让同一个 model_run 里的向量前后长度／含义不一致，
    而下游只按下标取值，不会察觉。正确做法是人工确认后开一个新的 model_version。
    """


def normalize(name: str) -> str:
    """列名归一：去空白 + 转大写。

    风格因子在接口里是全大写、行业因子是驼峰、CSV 导出全大写、协方差的行标签
    又是原大小写 —— 四种写法指同一个因子，匹配必须大小写不敏感。
    """
    return str(name).strip().upper()


def canonical(name: str) -> str | None:
    """把任意写法的因子名还原成规范名；不认识则返回 None。"""
    return _CANON.get(normalize(name))


def active_factors(df: pd.DataFrame) -> tuple[str, ...]:
    """从一份宽表里派生当日的活跃因子集合，按 `ALL_FACTORS` 的规范顺序排列。

    「活跃」= 该列存在且**不是整列缺失**。体系切换时旧体系专有的行业列会整列
    为 NaN，正是靠这一点区分。
    """
    present = {}
    for col in df.columns:
        name = canonical(col)
        if name is not None and df[col].notna().any():
            present[name] = True
    return tuple(f for f in ALL_FACTORS if f in present)


def factor_set_hash(factors: Sequence[str]) -> str:
    """因子**集合**的哈希（排序后），用于识别供应商换了因子集。"""
    joined = "|".join(sorted(normalize(f) for f in factors))
    return hashlib.md5(joined.encode()).hexdigest()


def factor_order_hash(factors: Sequence[str]) -> str:
    """因子**顺序**的哈希，用于识别本仓自己的排序规则被改动过。

    与集合哈希分开存两列：集合变了是供应商的事，顺序变了是我们的事，
    混成一个哈希就分不清该找谁。
    """
    joined = "|".join(normalize(f) for f in factors)
    return hashlib.md5(joined.encode()).hexdigest()


def reindex_wide(df: pd.DataFrame, order: Sequence[str]) -> np.ndarray:
    """按 `order` 从宽表取因子列，返回 ``(len(df), len(order))`` 的 float64 数组。

    **这是全仓唯一允许把宽表变成数组的入口。** 源列名经 `normalize` 匹配，
    缺列或重复列一律抛错 —— 不 fillna、不容忍。缺一列而用 0 补上，会让那个
    因子的暴露被系统性地当成「中性」，比整批失败难发现得多。
    """
    by_canon: dict[str, str] = {}
    for col in df.columns:
        name = canonical(col)
        if name is None:
            continue
        if name in by_canon:
            raise ValueError(f"宽表里因子 {name} 出现多列：{by_canon[name]} 与 {col}")
        by_canon[name] = col

    missing = [f for f in order if f not in by_canon]
    if missing:
        raise ValueError(f"宽表缺少因子列：{missing}")

    return df[[by_canon[f] for f in order]].to_numpy(dtype="float64")


def upper_triangle(matrix: np.ndarray) -> np.ndarray:
    """按**行优先上三角**（i ≤ j，i 外层）展平方阵，长度 K(K+1)/2。

    顺序必须与 `factor.covariance.cov_flat` 的列注释一致：用错顺序还原出来的
    矩阵**依然对称**，不会有任何报错，只是每个元素都对应错了因子对。
    """
    k = matrix.shape[0]
    if matrix.shape != (k, k):
        raise ValueError(f"不是方阵：{matrix.shape}")
    idx = np.triu_indices(k)
    return matrix[idx]


def from_upper_triangle(flat: Sequence[float], k: int) -> np.ndarray:
    """`upper_triangle` 的逆运算，还原成 K×K 对称方阵。供校验与下游使用。"""
    flat = np.asarray(flat, dtype="float64")
    expected = k * (k + 1) // 2
    if flat.size != expected:
        raise ValueError(f"展平长度 {flat.size} 与 K={k} 不符（应为 {expected}）")
    out = np.zeros((k, k), dtype="float64")
    idx = np.triu_indices(k)
    out[idx] = flat
    return out + np.triu(out, k=1).T
