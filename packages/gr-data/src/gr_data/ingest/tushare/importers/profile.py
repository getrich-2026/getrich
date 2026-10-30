"""Tushare 主数据快照 → meta.*_profile（标的档案）。

`meta.instruments` 只存跨资产共用的身份字段；股票、指数、期货主数据接口里其余的
描述性字段落到各自的档案表，一个源字段只落一处：

| raw | 目标表 |
|---|---|
| ``instruments/stock.parquet``（stock_basic）| ``meta.stock_profile`` |
| ``instruments/index.parquet``（index_basic）| ``meta.index_profile`` |
| ``instruments/future.parquet``（fut_basic）| ``meta.future_profile`` |

全部是**最新快照**，不是历史 PIT。raw 缺档案字段（扩字段前采集的旧快照）时硬失败，
提示重新采集 ``instruments``，而不是把整列写成 NULL 覆盖库内已有值。
"""

from __future__ import annotations

from typing import ClassVar

import pandas as pd

from gr_data.common import contracts
from gr_data.ingest.base import BaseImporter, IngestGateError
from gr_data.ingest.resolve import resolve_by_instrument
from gr_data.ingest.tushare.adapter import TushareAdapter
from gr_data.ingest.tushare.importers.reference import _clean_codes, parse_date


PROVIDER = "tushare"


def _text(series: pd.Series) -> pd.Series:
    """去首尾空白；缺失与空串统一为 None，不把 ``"nan"`` 之类的字面量写进库。"""
    cleaned = series.astype(object).where(series.notna(), None)
    return cleaned.map(lambda v: None if v is None or not str(v).strip() else str(v).strip())


def _number(series: pd.Series, field: str) -> pd.Series:
    """严格转数值：缺失保持 None，无法解析的值硬失败而不是静默变 NULL。"""
    present = series.notna() & series.astype(str).str.strip().ne("")
    parsed = pd.to_numeric(series.where(present), errors="coerce")
    bad = present & parsed.isna()
    if bad.any():
        samples = series[bad].head(5).tolist()
        raise IngestGateError(f"Non-numeric {field} values samples={samples}")
    return parsed.astype(object).where(parsed.notna(), None)


class _ProfileImporter(BaseImporter):
    """档案 importer 的公共流程：读主数据快照 → 解析身份 → 按字段映射输出。"""

    PROVIDER = PROVIDER
    STRICT_QUALITY = True
    NOT_NULL_COLUMNS = ("instrument_id", "source")

    ASSET: ClassVar[str] = ""
    API: ClassVar[str] = ""
    #: 目标列 → 源字段，按 contract 列序；类型由下面两组决定，其余为文本。
    FIELDS: ClassVar[tuple[tuple[str, str], ...]] = ()
    DATE_COLUMNS: ClassVar[frozenset[str]] = frozenset()
    NUMERIC_COLUMNS: ClassVar[frozenset[str]] = frozenset()
    #: 主数据缺失时是否硬失败（股票是全部按月数据的前提，其余资产可软跳过）。
    REQUIRED: ClassVar[bool] = False

    def build(self) -> pd.DataFrame:
        raw = TushareAdapter(self.paths).read_instruments(self.ASSET)
        if raw is None or raw.empty:
            message = f"instruments[{self.ASSET}] raw is missing or empty"
            if self.REQUIRED:
                raise IngestGateError(message)
            self._soft(f"{message}; skipped")
            return pd.DataFrame(columns=list(self.contract.columns))
        sources = {source for _, source in self.FIELDS}
        missing = {"ts_code", *sources} - set(raw.columns)
        if missing:
            raise IngestGateError(
                f"{self.API} 缺少档案字段 {sorted(missing)}；请重新采集 tushare instruments"
            )
        frame = _clean_codes(raw, self.API)
        ids = resolve_by_instrument(self.conn, self.ASSET)
        instrument_id = frame["ts_code"].map(ids)
        unknown = instrument_id.isna()
        if unknown.any():
            # 档案只补充已登记的身份；未登记代码说明 instruments 尚未导入同一份快照。
            samples = frame.loc[unknown, "ts_code"].head(5).tolist()
            raise IngestGateError(
                f"Unregistered {self.ASSET} codes count={int(unknown.sum())} samples={samples}"
            )

        out = pd.DataFrame({"instrument_id": instrument_id.astype("int64")})
        for column, source in self.FIELDS:
            values = frame[source]
            if column in self.DATE_COLUMNS:
                out[column] = values.map(parse_date)
            elif column in self.NUMERIC_COLUMNS:
                out[column] = _number(values, f"{self.API}.{source}")
            else:
                out[column] = _text(values)
        out["source"] = PROVIDER
        self._validate(out)
        return out[list(self.contract.columns)].reset_index(drop=True)

    def _validate(self, out: pd.DataFrame) -> None:
        """子类追加枚举等业务校验；默认不做额外检查。"""


class StockProfileImporter(_ProfileImporter):
    """stock_basic → meta.stock_profile。"""

    DATASET = "stock_profile"
    CONTRACT = contracts.STOCK_PROFILE
    ASSET = "stock"
    API = "stock_basic"
    REQUIRED = True
    FIELDS = (
        ("fullname", "fullname"),
        ("enname", "enname"),
        ("cnspell", "cnspell"),
        ("area", "area"),
        ("industry", "industry"),
        ("board", "market"),
        ("is_hs", "is_hs"),
        ("currency", "curr_type"),
        ("act_name", "act_name"),
        ("act_ent_type", "act_ent_type"),
    )

    def _validate(self, out: pd.DataFrame) -> None:
        # 枚举外的值意味着源语义变了；DDL CHECK 会拒掉整批，这里先给出可定位的取值。
        bad = out["is_hs"].notna() & ~out["is_hs"].isin(["N", "H", "S"])
        if bad.any():
            raise IngestGateError(
                f"Unknown stock_basic.is_hs values={sorted(set(out['is_hs'][bad]))}"
            )


class IndexProfileImporter(_ProfileImporter):
    """index_basic → meta.index_profile。"""

    DATASET = "index_profile"
    CONTRACT = contracts.INDEX_PROFILE
    ASSET = "index"
    API = "index_basic"
    FIELDS = (
        ("fullname", "fullname"),
        ("publish_market", "market"),
        ("publisher", "publisher"),
        ("index_type", "index_type"),
        ("category", "category"),
        ("base_date", "base_date"),
        ("base_point", "base_point"),
        ("weight_rule", "weight_rule"),
        ("description", "desc"),
    )
    DATE_COLUMNS = frozenset({"base_date"})
    NUMERIC_COLUMNS = frozenset({"base_point"})


class FutureProfileImporter(_ProfileImporter):
    """fut_basic → meta.future_profile；乘数与最小变动价位不在此表（见 meta.future_contracts）。"""

    DATASET = "future_profile"
    CONTRACT = contracts.FUTURE_PROFILE
    ASSET = "future"
    API = "fut_basic"
    FIELDS = (
        ("product_code", "fut_code"),
        ("trade_unit", "trade_unit"),
        ("per_unit", "per_unit"),
        ("quote_unit", "quote_unit"),
        ("quote_unit_desc", "quote_unit_desc"),
        ("delivery_mode", "d_mode_desc"),
        ("delivery_month", "d_month"),
        ("delivery_date", "last_ddate"),
        ("trade_time_desc", "trade_time_desc"),
    )
    DATE_COLUMNS = frozenset({"delivery_date"})
    NUMERIC_COLUMNS = frozenset({"per_unit"})
