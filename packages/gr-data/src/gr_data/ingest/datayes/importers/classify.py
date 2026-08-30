"""DataYes exposure 的行业哑变量 → `classify` schema（缺口 G1，申万一级）。

## 为什么用风险模型的暴露表推行业

G1 的**正解**是 tushare 的 `index_classify` + `index_member_all`：三级树、官方
代码、真实生效日期。但那两个接口在 `getrich-design` 的字段目录里还没有文档，
凭猜实现会写出一批看起来对、实际对不上申万发布口径的数据。

通联 CNE6 的 exposure 表里，31 个行业因子是 0/1 哑变量、每行恰有一个 1，
因此每个交易日的行业归属是可以**无歧义读出来**的。代价是五条硬限制，全部写进
DDL 列注释与 `ops.data_quality_check`，不假装它们不存在：

1. 只覆盖 CNE6 收录的 A 股个股，不含 ETF / 指数 / 期货；
2. 只有一级（`scheme.available_level = 1`）；
3. `industry_code` 是通联的英文标识，不是申万官方码，`industry_node.external_code`
   留空待接到真源回填；
4. 没有真实 `in_date` —— 区间起点被导入窗口截短，窗口之前的行业归因整体缺行。
   方向是**保守**的：看不到更早的历史，而不是让历史看到未来；
5. 停牌日没有 exposure 行会打断区间，只对行业相同的相邻段做有限度的空洞合并。

接到 tushare 真源后，本表走 `gr-data own release/set` 转移归属，
两个来源的分歧本身就是很强的质量信号。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from gr_data.common import contracts
from gr_data.ingest.datayes import factors as fx
from gr_data.ingest.datayes.importers.riskmodel import (
    PROVIDER,
    _available_at,
    _DatayesImporter,
    _trading_day,
)


#: 申万 2021 一级体系在本仓的标识。体系改版视为新增 scheme_code，维表不做版本。
SCHEME_CODE = "sw2021"
SCHEME_NAME = "申万行业分类 2021 版"
LEVEL = 1

#: 允许跨过的最大空洞（自然日）。停牌、长期停牌复牌都会让 exposure 缺行，
#: 而缺行不等于换了行业。超过这个跨度就断开成两段 —— 一年不交易的票，
#: 中间是不是被重分类过，我们并不知道，接上等于替供应商编数据。
MAX_GAP_DAYS = 40


class SchemeImporter(_DatayesImporter):
    """登记 classify.scheme 的 sw2021 一行。"""

    DATASET = "scheme"
    DATASET_RAW = "exposure_cne6_sw21"
    CONTRACT = contracts.SCHEME
    NOT_NULL_COLUMNS = ("scheme_code", "scheme_name", "max_level", "available_level", "source")

    def build(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "scheme_code": SCHEME_CODE,
                    "scheme_name": SCHEME_NAME,
                    # 申万 2021 共三级；本源只覆盖一级，两个数字的差就是覆盖缺口本身。
                    "max_level": 3,
                    "available_level": LEVEL,
                    "source": PROVIDER,
                }
            ],
            columns=list(self.contract.columns),
        )


class IndustryNodeImporter(_DatayesImporter):
    """把 31 个申万 2021 一级行业写进维表。

    节点表来自 `factors.py` 的常量（同一份常量也决定了因子数组的下标），
    **不从数据里现推** —— 某天全市场恰好没有某个行业的票，现推就会少一个节点，
    而 `instrument_industry` 的 FK 会在下一天该行业重新出现时炸掉。
    """

    DATASET = "industry_node"
    DATASET_RAW = "exposure_cne6_sw21"
    CONTRACT = contracts.INDUSTRY_NODE
    NOT_NULL_COLUMNS = ("scheme_code", "level", "industry_code", "industry_name")

    def build(self) -> pd.DataFrame:
        rows = [
            {
                "scheme_code": SCHEME_CODE,
                "level": LEVEL,
                "industry_code": code,
                "industry_name": fx.INDUSTRY_NAMES[code],
                # 一级节点没有父节点；external_code 待接到申万官方码后回填。
                "parent_code": None,
                "external_code": None,
            }
            for code in fx.SW21_INDUSTRY_FACTORS
        ]
        return pd.DataFrame(rows, columns=list(self.contract.columns))


class InstrumentIndustryImporter(_DatayesImporter):
    """逐日行业归属 → 按变化点压缩成 (in_date, out_date) 区间。"""

    DATASET = "instrument_industry"
    DATASET_RAW = "exposure_cne6_sw21"
    CONTRACT = contracts.INSTRUMENT_INDUSTRY
    NOT_NULL_COLUMNS = (
        "instrument_id",
        "scheme_code",
        "level",
        "industry_code",
        "in_date",
        "source",
    )

    def build(self) -> pd.DataFrame:
        raw = self._raw()
        if raw.empty:
            self.log.warning("%s 无 raw 数据", self.DATASET_RAW)
            return self._empty()

        df = self._attach_instrument_ids(raw)
        if df.empty:
            return self._empty()

        _, factor_order = self._run_and_order(raw)
        daily = self._daily_industry(df, factor_order)
        if daily.empty:
            return self._empty()

        intervals = _compress(daily)

        window_start = daily["trading_day"].min()
        self._record_dq(
            "classify_window_truncated",
            "warn",
            {
                "scheme_code": SCHEME_CODE,
                "window_start": str(window_start),
                "detail": (
                    "in_date 是标的在导入窗口内首次出现的交易日，不是真实的行业生效日；"
                    f"{window_start} 之前的行业归属整体缺失"
                ),
            },
        )
        return intervals[list(self.contract.columns)].reset_index(drop=True)

    # -- 逐日行业 ------------------------------------------------------------
    def _daily_industry(self, df: pd.DataFrame, factor_order: list[str]) -> pd.DataFrame:
        """从哑变量矩阵读出每行的行业。

        走 `reindex_wide` 而不是按源列序取值 —— 三张宽表的列顺序互不相同，
        按源列序展平会把风格因子的 z-score 当成行业哑变量，而结果依然「有一个
        最大值」，取 argmax 照样出得来一个行业，静默全错。
        """
        ind_codes = [f for f in factor_order if fx.FACTOR_TYPE[f] == "industry"]
        if not ind_codes:
            raise ValueError("model_run 的因子顺序里没有任何行业因子")

        values = fx.reindex_wide(df, ind_codes)
        filled = np.nan_to_num(values, nan=0.0)

        # 每行恰有一个 1 是硬校验，不做「取最大值」兜底：兜底正好会把列错位
        # 或体系切换掩盖过去，而那两件事都必须让人看见。
        row_sum = filled.sum(axis=1)
        bad = ~np.isclose(row_sum, 1.0)
        if bad.any():
            raise ValueError(
                f"{int(bad.sum())} 行的行业哑变量之和不为 1（样例 {row_sum[bad][:5].tolist()}）"
                " —— 通常意味着因子列错位或供应商换了行业体系"
            )

        out = pd.DataFrame(
            {
                "instrument_id": df["instrument_id"].astype("int64").to_numpy(),
                "trading_day": _trading_day(df).to_numpy(),
                "industry_code": np.array(ind_codes)[filled.argmax(axis=1)],
                "available_at": _available_at(df).to_numpy(),
            }
        )
        # 同一天同一标的重复出现（跨月 parquet 有重叠）时保留最后一条
        return out.drop_duplicates(subset=["instrument_id", "trading_day"], keep="last")


def _compress(daily: pd.DataFrame) -> pd.DataFrame:
    """逐日行业 → 区间。

    切段的两个条件：行业变了，或者与上一条的间隔超过 `MAX_GAP_DAYS`。
    `out_date` 取**下一段的起点**（半开区间 `[in_date, out_date)`），最后一段留
    NULL 表示当前有效 —— 用「本段最后一个交易日」当 out_date 会在两段之间留下
    一天的空档，那一天查不到任何行业。
    """
    df = daily.sort_values(["instrument_id", "trading_day"]).reset_index(drop=True)

    day = pd.to_datetime(df["trading_day"])
    same_iid = df["instrument_id"].eq(df["instrument_id"].shift())
    same_ind = df["industry_code"].eq(df["industry_code"].shift())
    small_gap = (day - day.shift()).dt.days.le(MAX_GAP_DAYS)
    df["_seg"] = (~(same_iid & same_ind & small_gap)).cumsum()

    grouped = df.groupby("_seg", sort=True)
    seg = pd.DataFrame(
        {
            "instrument_id": grouped["instrument_id"].first(),
            "industry_code": grouped["industry_code"].first(),
            "in_date": grouped["trading_day"].first(),
            # available_at 取本段最早一条：这一段的行业归属从那一刻起才可用。
            "available_at": grouped["available_at"].first(),
        }
    ).reset_index(drop=True)

    # 同一标的的下一段起点即本段终点；最后一段为 NULL（当前有效）。
    next_in = seg["in_date"].shift(-1)
    next_same_iid = seg["instrument_id"].eq(seg["instrument_id"].shift(-1))
    seg["out_date"] = next_in.where(next_same_iid, None)

    seg["scheme_code"] = SCHEME_CODE
    seg["level"] = LEVEL
    seg["source"] = PROVIDER
    return seg
