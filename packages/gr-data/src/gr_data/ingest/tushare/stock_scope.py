"""股票导入范围：B 股仅登记范围外观察，raw 不改、不映射到 A 股。"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import numpy as np
import pandas as pd

from gr_data.ingest.base import BaseImporter, IngestGateError
from gr_data.ingest.tushare.adapter import TushareAdapter


B_SHARE_PATTERN = r"(?:900[0-9]{3}\.SH|200[0-9]{3}\.SZ)"
B_SHARE_RULE = "tushare_b_share_out_of_scope"
B_SHARE_EXCEPTIONS = frozenset({"201872.SZ"})
B_SHARE_201872_EVIDENCE = (
    "https://static.cninfo.com.cn/finalpage/2018-12-26/1205690369.PDF",
    "https://www.szse.cn/disclosure/notice/general/t20181221_563712.html",
)
_STOCK_DATASETS = frozenset({"daily", "adj_factor", "daily_basic", "stk_limit", "suspend_d"})
_PRIMARY = {
    "stock_bar_1d": "daily",
    "adj_factor_ts": "adj_factor",
    "valuation_1d": "daily_basic",
    "suspend_d": "suspend_d",
    "instruments": "instruments/stock",
    "stock_profile": "instruments/stock",
    "symbol_map": "symbol_map",
}


def raw_json(value: object) -> object:
    """保留源值；NaN／Inf 用文字标记，不丢失原观察的缺失／极值语义。"""
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, np.generic):
        return raw_json(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, (date, datetime, Decimal)):
        return str(value)
    if isinstance(value, dict):
        return {str(k): raw_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [raw_json(v) for v in value]
    return value


def b_share_mask(codes: pd.Series) -> pd.Series:
    """仅两常规号段及已核实的 201872；单例实际排除前另查无映射前提。"""
    normalized = codes.astype("string").str.strip()
    return normalized.str.fullmatch(B_SHARE_PATTERN, na=False) | normalized.isin(B_SHARE_EXCEPTIONS)


class StockScopeImporter(BaseImporter):
    """共享范围过滤及事务审计；全为范围外观察与真正的空源文件分开。"""

    _stock_scope_all_excluded = False

    def _check_quality(self, df: pd.DataFrame) -> list[str]:
        if df.empty and self._stock_scope_all_excluded:
            return []
        return super()._check_quality(df)

    def exclude_b_shares(
        self, frame: pd.DataFrame, dataset: str, partition: str, *, code_column: str = "ts_code"
    ) -> pd.DataFrame:
        """按精确代码段排除并登记；审计与目标写入共用调用方事务。

        不解析范围外行的日期或价格；缺列、坏文件及所有范围内校验仍由原流程拒绝。
        审计以目标、批次和原观察指纹去重，回滚后重试仍会重新登记。
        """
        if code_column not in frame:
            return frame
        exception = frame[code_column].astype("string").str.strip().isin(B_SHARE_EXCEPTIONS)
        if exception.any():
            # 仅放行这个已核实 B 股的缺映射；已有映射、连接／查询等失败一律向上传播。
            # 不能借范围规则隐藏错误的 B→A 映射，也不新增任何证券或来源映射。
            if self.conn is None:
                raise IngestGateError(
                    "Cannot verify missing mapping for B-share exception 201872.SZ"
                )
            mapped = self.conn.execute(
                "SELECT 1 FROM meta.symbol_map WHERE source='tushare' "
                "AND source_symbol='201872.SZ' LIMIT 1"
            ).fetchone()
            if mapped is not None:
                raise IngestGateError(
                    "B-share exception 201872.SZ requires missing mapping; existing mapping found"
                )
        mask = b_share_mask(frame[code_column])
        if dataset == _PRIMARY.get(self.DATASET):
            counts = getattr(self, "_stock_scope_counts", {})
            counts[dataset, partition] = (len(frame), int((~mask).sum()))
            self._stock_scope_counts = counts
            self._stock_scope_all_excluded = (
                sum(n for n, _ in counts.values()) > 0 and sum(n for _, n in counts.values()) == 0
            )
        if not mask.any():
            return frame
        if self.conn is not None:
            batch = getattr(self, "_stock_scope_batch", None)
            if batch is None:
                batch = self.ctx.batch_id or uuid4().hex
                if not batch.strip() or len(batch) > 128:
                    raise ValueError("Invalid stock scope batch_id")
                self._stock_scope_batch = batch
            records = {}
            offsets = np.flatnonzero(mask.to_numpy(dtype=bool))
            for offset, row in zip(
                offsets, frame.iloc[offsets].to_dict(orient="records"), strict=True
            ):
                original = raw_json(row)
                payload = json.dumps(original, sort_keys=True, ensure_ascii=False, allow_nan=False)
                code = str(row[code_column]).strip()
                identity = f"{dataset}:{partition}:{offset}:{payload}"
                detail = {
                    "provider": "tushare",
                    "dataset": dataset,
                    "partition": partition,
                    "source_code": code,
                    "source_date": raw_json(row.get("trade_date")),
                    "target": self.contract.qualified,
                    "batch_id": batch,
                    "rule": (
                        "verified_201872.SZ_missing_mapping"
                        if code in B_SHARE_EXCEPTIONS
                        else "900xxx.SH/200xxx.SZ"
                    ),
                    "disposition": "out_of_scope",
                    "raw_values": original,
                    "raw_preserved": True,
                    "observation_id": hashlib.sha256(identity.encode()).hexdigest(),
                }
                if code in B_SHARE_EXCEPTIONS:
                    detail.update(
                        mapping_missing_verified=True,
                        evidence_urls=list(B_SHARE_201872_EVIDENCE),
                    )
                records[detail["observation_id"]] = (
                    B_SHARE_RULE,
                    "info",
                    json.dumps(detail, ensure_ascii=False),
                )
            with self.conn.cursor() as cur:
                # 同目标／批次串行登记，重复读取或重跑不重复占一条范围外观察。
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"{B_SHARE_RULE}:{self.contract.qualified}:{batch}",),
                )
                cur.execute(
                    "SELECT detail->>'observation_id' FROM ops.data_quality_check "
                    "WHERE rule=%s AND detail->>'target'=%s AND detail->>'batch_id'=%s",
                    (B_SHARE_RULE, self.contract.qualified, batch),
                )
                existing = {row[0] for row in cur.fetchall()}
                pending = [record for key, record in records.items() if key not in existing]
                if pending:
                    cur.executemany(
                        "INSERT INTO ops.data_quality_check(rule,severity,detail) "
                        "VALUES (%s,%s,%s)",
                        pending,
                    )

        self.log.info(
            "B-share observations out of scope dataset=%s partition=%s rows=%d target=%s",
            dataset,
            partition,
            int(mask.sum()),
            self.contract.qualified,
        )
        return frame.loc[~mask].copy()


class StockScopeAdapter(TushareAdapter):
    """在 importer 的读取边界应用范围规则；原始适配器及 raw 文件保持不变。"""

    def __init__(self, importer: StockScopeImporter):
        super().__init__(importer.paths, importer.ctx.months)
        self.importer = importer

    def read_month(self, dataset: str, ym: str) -> pd.DataFrame | None:
        frame = super().read_month(dataset, ym)
        if frame is not None and dataset in _STOCK_DATASETS:
            return self.importer.exclude_b_shares(frame, dataset, ym)
        return frame

    def read_instruments(self, asset: str) -> pd.DataFrame | None:
        frame = super().read_instruments(asset)
        if asset == "stock" and frame is not None:
            return self.importer.exclude_b_shares(frame, "instruments/stock", "snapshot")
        return frame
