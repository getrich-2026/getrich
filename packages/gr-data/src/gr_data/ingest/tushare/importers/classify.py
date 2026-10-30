"""meta.instruments → classify.instrument_category（资产类别，缺口 G5）。

这是**纯规则映射**，不读 raw parquet：输入是已经入库的 `meta.instruments`，
ETF 另读 `meta.etf_profile`（etf_basic + fund_basic 快照）。
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
#:   etf    不在这里：按 meta.etf_profile 的 fund_type 与投资通道映射，见下方两张表
#: 刻意**不列**的：
#:   fund   没有任何 importer 产出，也没有投资类型可依据
#:   index  指数不是可持有标的，给它一个资产类别没有意义
#:   future 交易所定不了类别 —— CFFEX 同时有股指期货（equity）与国债期货
#:          （fixed_income），必须逐品种判断，而本仓没有品种到类别的权威映射
#:   option 同上，且还要看标的资产
_CATEGORY_BY_ASSET: dict[str, tuple[str, str]] = {
    "stock": ("equity", "cn_a"),
}

#: fund_basic.fund_type → asset_category。2026-10-30 全名单核验：旧的「ETF 一律 equity」
#: 被 62 只债券型、30 只货币型反例证伪。「其他」（黄金等）与混合型无法唯一确定类别，
#: 不按名称或业绩基准猜，不写行。
_ETF_CATEGORY_BY_FUND_TYPE: dict[str, str] = {
    "股票型": "equity",
    "债券型": "fixed_income",
    "货币型": "cash",
}
#: etf_basic.etf_type → market。QDII 投向境外，具体是 hk／us 还是其他市场源未给出，不写行。
_ETF_MARKET_BY_CHANNEL: dict[str, str] = {"纯境内": "cn_a"}


class InstrumentCategoryImporter(BaseImporter):
    """按规则给 A 股 / ETF 打资产类别与市场标签；无法确定的标的不写并记录质量检查。"""

    PROVIDER = PROVIDER
    DATASET = "instrument_category"
    CONTRACT = contracts.INSTRUMENT_CATEGORY
    NOT_NULL_COLUMNS = ("instrument_id", "asset_category", "market", "in_date", "source")
    STRICT_QUALITY = True

    def build(self) -> pd.DataFrame:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT i.instrument_id, i.asset, i.list_date, i.delist_date, "
                "       p.fund_type, p.channel "
                "FROM meta.instruments i "
                "LEFT JOIN meta.etf_profile p USING (instrument_id) "
                "WHERE i.asset = ANY(%s)",
                (sorted({*_CATEGORY_BY_ASSET, "etf"}),),
            )
            rows = cur.fetchall()

        if not rows:
            self.log.warning("meta.instruments 里没有可分类的标的，请先运行 instruments importer")
            return pd.DataFrame(columns=list(self.contract.columns))

        df = pd.DataFrame(
            rows,
            columns=["instrument_id", "asset", "list_date", "delist_date", "fund_type", "channel"],
        )
        scope = [int(iid) for iid in df["instrument_id"]]
        df["asset_category"] = df["asset"].map({a: c for a, (c, _) in _CATEGORY_BY_ASSET.items()})
        df["market"] = df["asset"].map({a: m for a, (_, m) in _CATEGORY_BY_ASSET.items()})
        etf = df["asset"].eq("etf")
        df.loc[etf, "asset_category"] = df.loc[etf, "fund_type"].map(_ETF_CATEGORY_BY_FUND_TYPE)
        df.loc[etf, "market"] = df.loc[etf, "channel"].map(_ETF_MARKET_BY_CHANNEL)
        # 分不出类别或市场的 ETF 不写：写错一行比少一行危害大（见模块说明）。
        unmapped = etf & (df["asset_category"].isna() | df["market"].isna())
        if unmapped.any():
            skipped = df[unmapped]
            self._record_skipped(
                "classify_category_etf_unmapped",
                skipped,
                {
                    "by_fund_type": skipped["fund_type"].fillna("<no_profile>").value_counts(),
                    "by_channel": skipped["channel"].fillna("<no_profile>").value_counts(),
                },
            )
            df = df[~unmapped]

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

        out = pd.DataFrame(
            {
                "instrument_id": df["instrument_id"].astype("int64"),
                "asset_category": df["asset_category"],
                "market": df["market"],
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
        out = out[list(self.contract.columns)].reset_index(drop=True)
        self._retire_stale(scope, out)
        return out

    def _retire_stale(self, scope: list[int], out: pd.DataFrame) -> None:
        """删除本次范围内未重新产出的旧分类，与随后的写入同一事务提交。

        每次重导都是整个股票／ETF 范围的完整快照：某只 ETF 由股票型变为「其他」、QDII
        或失去档案时，只跳过写入会让旧的 equity 行继续生效，诊断无法降级。这里删除而不是
        填 out_date：in_date 本就是按上市日回填的当前快照，不是历史时点，编一个「今天失效」
        反而是伪造时点（与 D-026「删除后按上市日重写」一致）。上市日变更后旧 in_date 的行
        同样在此清除。失败时调用方回滚整个事务，不会只删不写。
        """
        with self.conn.cursor() as cur:
            cur.execute(
                "DELETE FROM classify.instrument_category c "
                "WHERE c.source = %s AND c.instrument_id = ANY(%s) AND NOT EXISTS ("
                "  SELECT 1 FROM unnest(%s::bigint[], %s::date[]) AS k(iid, in_date) "
                "  WHERE k.iid = c.instrument_id AND k.in_date = c.in_date"
                ") RETURNING c.instrument_id",
                (
                    PROVIDER,
                    scope,
                    [int(x) for x in out["instrument_id"]],
                    list(out["in_date"]),
                ),
            )
            retired = pd.DataFrame(cur.fetchall(), columns=["instrument_id"])
        if not retired.empty:
            self._record_skipped("classify_category_retired", retired)

    def _record_skipped(
        self,
        rule: str,
        skipped: pd.DataFrame,
        breakdown: dict[str, pd.Series] | None = None,
    ) -> None:
        detail: dict[str, object] = {
            "count": int(len(skipped)),
            "sample": [int(x) for x in skipped["instrument_id"].head(20)],
        }
        for key, counts in (breakdown or {}).items():
            detail[key] = {str(k): int(v) for k, v in counts.items()}
        self.log.warning("%s：跳过 %d 个标的", rule, detail["count"])
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ops.data_quality_check (rule, severity, detail) VALUES (%s, %s, %s)",
                (rule, "warn", json.dumps(detail, ensure_ascii=False)),
            )
