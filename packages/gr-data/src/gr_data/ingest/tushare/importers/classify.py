"""meta.instruments → classify.instrument_category（资产类别，缺口 G5）。

这是**纯规则映射**，不读 raw parquet：输入就是已经入库的 `meta.instruments`。
之所以不直接用 `meta.instruments.asset`，是因为那一列是**品种级**取值
（stock/etf/index/future/option/fund），而持仓诊断要的是**资产类别**
（equity / fixed_income / commodity / cash / alternative）。两者不是一回事：
国债期货是 future 但属固收，股指期货是 future 却属权益。

映射只覆盖能确定的部分，**不确定的一律不写**（见 `_CATEGORY_BY_ASSET` 的注释）。
少一行的后果是下游对该标的标 degraded，写错一行的后果是资产配置分解整块失真
且不会报错 —— 两者不对称，所以宁缺毋滥。
"""

from __future__ import annotations

import json

import pandas as pd

from gr_data.common import contracts
from gr_data.ingest import pit
from gr_data.ingest.base import BaseImporter


PROVIDER = "tushare"

#: asset → (asset_category, market)。**只列能确定的**：
#:   stock  A 股个股，权益无疑问
#:   etf    一律记 equity。区分股票型与债券型 ETF 需要基金持仓明细（缺口 G4，
#:          一期不处理），按名称猜会把债基误判成权益。这条限制写在 DDL 列注释里。
#:   fund   同上
#: 刻意**不列**的：
#:   index  指数不是可持有标的，给它一个资产类别没有意义
#:   future 交易所定不了类别 —— CFFEX 同时有股指期货（equity）与国债期货
#:          （fixed_income），必须逐品种判断，而本仓没有品种到类别的权威映射
#:   option 同上，且还要看标的资产
_CATEGORY_BY_ASSET: dict[str, tuple[str, str]] = {
    "stock": ("equity", "cn_a"),
    "etf": ("equity", "cn_a"),
    "fund": ("equity", "cn_a"),
}


class InstrumentCategoryImporter(BaseImporter):
    """按规则给 A 股 / ETF 打资产类别与市场标签。"""

    PROVIDER = PROVIDER
    DATASET = "instrument_category"
    CONTRACT = contracts.INSTRUMENT_CATEGORY
    NOT_NULL_COLUMNS = ("instrument_id", "asset_category", "market", "in_date", "source")

    def build(self) -> pd.DataFrame:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT instrument_id, asset, list_date, delist_date "
                "FROM meta.instruments WHERE asset = ANY(%s)",
                (sorted(_CATEGORY_BY_ASSET),),
            )
            rows = cur.fetchall()

        if not rows:
            self.log.warning("meta.instruments 里没有可分类的标的，请先运行 instruments importer")
            return pd.DataFrame(columns=list(self.contract.columns))

        df = pd.DataFrame(rows, columns=["instrument_id", "asset", "list_date", "delist_date"])

        # in_date 必须有值：它是主键的一部分，也是「这一分类从何时起有效」的唯一依据。
        # 上市日缺失时跳过而不是拿今天顶上 —— 拿今天顶会让这条分类看起来是新生效的，
        # 回溯到历史区间时整只票查不到分类。
        no_list_date = df["list_date"].isna()
        if no_list_date.any():
            self._record_skipped("classify_category_missing_list_date", df[no_list_date])
            df = df[~no_list_date]

        # chk_date_order 要求 out_date > in_date；相等或倒挂的行是源数据错误，
        # 直接入库会被 CHECK 拒掉整批，这里先剔出来留痕。
        bad_range = df["delist_date"].notna() & (df["delist_date"] <= df["list_date"])
        if bad_range.any():
            self._record_skipped("classify_category_bad_date_range", df[bad_range])
            df = df[~bad_range]

        if df.empty:
            return pd.DataFrame(columns=list(self.contract.columns))

        mapped = df["asset"].map(_CATEGORY_BY_ASSET)
        out = pd.DataFrame(
            {
                "instrument_id": df["instrument_id"].astype("int64"),
                "asset_category": mapped.str[0],
                "market": mapped.str[1],
                "in_date": pd.to_datetime(df["list_date"]).dt.date,
                "out_date": pd.to_datetime(df["delist_date"]).dt.date.where(
                    df["delist_date"].notna(), None
                ),
                # 分类在上市当天就已确定，没有额外的披露延迟，取上市日 00:00。
                "available_at": pit.from_trading_day(
                    pd.to_datetime(df["list_date"]).dt.date, publish_hour=0
                ),
                "source": PROVIDER,
            }
        )
        return out[list(self.contract.columns)].reset_index(drop=True)

    def _record_skipped(self, rule: str, skipped: pd.DataFrame) -> None:
        detail = {
            "count": int(len(skipped)),
            "sample": [int(x) for x in skipped["instrument_id"].head(20)],
        }
        self.log.warning("%s：跳过 %d 个标的", rule, detail["count"])
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ops.data_quality_check (rule, severity, detail) VALUES (%s, %s, %s)",
                (rule, "warn", json.dumps(detail, ensure_ascii=False)),
            )
