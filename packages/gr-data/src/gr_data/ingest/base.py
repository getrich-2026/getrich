"""ingest 层基类。

ingest 职责：读 raw parquet（或直连 SDK）→ 归一化为 canonical → 写 PostgreSQL。
每个 Importer 对应一张目标表，写库前：
1. 经 OwnershipManager 校验/登记归属（单表单一 provider）。
2. 经 quality 校验（空集/缺列/重复键/null）。
3. upsert 进目标表（临时表 + COPY + ON CONFLICT）。
4. 在 ops.etl_job_run 记一条运行流水。

见 docs/layers/ingest.md。
"""

from __future__ import annotations

import abc
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from gr_data.common.contracts import TableContract
from gr_data.common.ownership import OwnershipManager
from gr_data.common.paths import RawPaths
from gr_data.common.quality import check_dataframe
from gr_data.db.copy import upsert_rows
from gr_data.logging import get_logger


def _json_safe(value: Any) -> Any:
    """把 dict/list 里 PG 的 jsonb 不接受的值换掉。

    要处理的有三类：NaN/Inf（`json.dumps` 会产出 `NaN`/`Infinity` 字面量，
    不是合法 JSON，PG 直接拒绝整批）、numpy 标量（`json` 不认）、
    pandas 的 NaT/NA。**只做无损的类型转换，不做数值兜底** —— 缺失就是 None。
    """
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if value is None or value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value


@dataclass
class IngestContext:
    paths: RawPaths
    channel: str = "ingest"
    force_ownership: bool = False  # True=允许转移归属

    #: 只处理这些自然月（``("2025-01", "2025-02")``）；None = 全部。
    #:
    #: 存在的理由是**内存**：importer 的 `build()` 是「读全部月份 → 拼一个大
    #: DataFrame → 一次 upsert」的形态，对 tushare 日线（164 个月 × 11 万行）和
    #: datayes exposure（61 个月 × 11 万行 × 58 列）会吃掉几个 GB，在小内存机器上
    #: 直接 OOM。按月分批调用 `run()` 可以把峰值压到单月量级，代价是每月一条
    #: `ops.etl_job_run`（这反而让「哪个月入过库」可追溯）。
    #: 默认 None 时行为与以前完全一致。
    months: tuple[str, ...] | None = None


@dataclass
class IngestResult:
    dataset: str
    target: str
    rows_written: int
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.warnings


class BaseImporter(abc.ABC):
    """所有 ingest importer 的基类。"""

    PROVIDER: str = ""
    DATASET: str = ""
    CONTRACT: TableContract | None = None

    # quality 校验参数（子类可覆盖）
    NOT_NULL_COLUMNS: tuple[str, ...] = ()

    # 需要特殊装箱的列（必须是 contract.columns 的子集）。
    # 普通列走 `astype(object).where(notna)` 的标量化路径就够了，但这两类不行：
    #   ARRAY_COLUMNS：值可能是 np.ndarray，psycopg 不认，得先 .tolist()
    #   JSON_COLUMNS ：dict 要包成 Jsonb，且内部的 NaN 必须先换成 None ——
    #                  json.dumps(float("nan")) 产出 `NaN` 字面量，PG 的 jsonb
    #                  解析器会直接拒绝，整批 COPY 失败
    ARRAY_COLUMNS: tuple[str, ...] = ()
    JSON_COLUMNS: tuple[str, ...] = ()

    def __init__(self, conn: psycopg.Connection, ctx: IngestContext, client: Any | None = None):
        self.conn = conn
        self.ctx = ctx
        self.client = client  # 直连 SDK 时用；读 parquet 模式可为 None
        self.log = get_logger(f"ingest.{self.PROVIDER}.{self.DATASET}")

    @property
    def paths(self) -> RawPaths:
        return self.ctx.paths

    @property
    def contract(self) -> TableContract:
        if self.CONTRACT is None:
            raise NotImplementedError(f"{type(self).__name__} 未声明 CONTRACT")
        return self.CONTRACT

    @abc.abstractmethod
    def build(self) -> pd.DataFrame:
        """读 raw 并归一化为 canonical DataFrame（列与 contract.columns 对齐）。"""
        raise NotImplementedError

    def _check_quality(self, df: pd.DataFrame) -> list[str]:
        rep = check_dataframe(
            df,
            dataset=f"{self.PROVIDER}.{self.DATASET}",
            required_columns=list(self.contract.columns),
            key_columns=list(self.contract.conflict_keys),
            not_null_columns=list(self.NOT_NULL_COLUMNS),
        )
        if not rep.ok:
            self.log.warning("质量校验问题: %s", rep.issues)
        return rep.issues

    def _df_to_rows(self, df: pd.DataFrame) -> list[tuple]:
        cols = list(self.contract.columns)
        special = set(self.ARRAY_COLUMNS) | set(self.JSON_COLUMNS)
        unknown = special - set(cols)
        if unknown:
            # 列名拼错时当场报错，而不是「声明了但静默不生效」
            raise ValueError(f"{type(self).__name__} 的 ARRAY/JSON_COLUMNS 不在契约列里：{unknown}")

        plain = [c for c in cols if c not in special]
        # NaN/NaT -> None，供 psycopg 写 NULL
        out = df[cols].copy()
        if plain:
            out[plain] = df[plain].astype(object).where(pd.notna(df[plain]), None)
        for col in self.ARRAY_COLUMNS:
            out[col] = [None if v is None else list(v) for v in df[col]]
        for col in self.JSON_COLUMNS:
            out[col] = [None if v is None else Jsonb(_json_safe(v)) for v in df[col]]
        return [tuple(r) for r in out.itertuples(index=False, name=None)]

    def run(self) -> IngestResult:
        """执行入库（单事务）。"""
        target = self.contract.qualified
        owner = OwnershipManager(self.conn)
        # 归属校验/登记（首次写入即登记）
        owner.claim(target, self.PROVIDER, channel=self.ctx.channel, force=self.ctx.force_ownership)

        df = self.build()
        warnings = self._check_quality(df)

        rows = (
            self._df_to_rows(df) if not df.empty and "缺少必需列" not in " ".join(warnings) else []
        )
        written = 0
        if rows:
            written = upsert_rows(self.conn, self.contract, rows)
        self._record_run(written, warnings)
        self.conn.commit()
        self.log.info("入库完成 target=%s rows=%d warnings=%d", target, written, len(warnings))
        return IngestResult(
            dataset=self.DATASET, target=target, rows_written=written, warnings=warnings
        )

    def _record_run(self, rows_written: int, warnings: list[str]) -> None:
        status = "success" if not warnings else "partial"
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ops.etl_job_run
                  (job_name, provider, dataset_name, status, rows_written, warning_count,
                   started_at, finished_at)
                VALUES (%s, %s, %s, %s, %s, %s, now(), now())
                """,
                (
                    f"ingest.{self.PROVIDER}.{self.DATASET}",
                    self.PROVIDER,
                    self.DATASET,
                    status,
                    rows_written,
                    len(warnings),
                ),
            )
