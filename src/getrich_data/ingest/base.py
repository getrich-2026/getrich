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
from dataclasses import dataclass
from typing import Any

import pandas as pd
import psycopg

from getrich_data.common.contracts import TableContract
from getrich_data.common.db.copy import upsert_rows
from getrich_data.common.logging import get_logger
from getrich_data.common.ownership import OwnershipManager
from getrich_data.common.paths import RawPaths
from getrich_data.common.quality import check_dataframe


@dataclass
class IngestContext:
    paths: RawPaths
    channel: str = "ingest"
    force_ownership: bool = False  # True=允许转移归属


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
        # NaN/NaT -> None，供 psycopg 写 NULL
        clean = df[cols].astype(object).where(pd.notna(df[cols]), None)
        return [tuple(r) for r in clean.itertuples(index=False, name=None)]

    def run(self) -> IngestResult:
        """执行入库（单事务）。"""
        target = self.contract.qualified
        owner = OwnershipManager(self.conn)
        # 归属校验/登记（首次写入即登记）
        owner.claim(target, self.PROVIDER, channel=self.ctx.channel, force=self.ctx.force_ownership)

        df = self.build()
        warnings = self._check_quality(df)

        rows = self._df_to_rows(df) if not df.empty and "缺少必需列" not in " ".join(warnings) else []
        written = 0
        if rows:
            written = upsert_rows(self.conn, self.contract, rows)
        self._record_run(written, warnings)
        self.conn.commit()
        self.log.info("入库完成 target=%s rows=%d warnings=%d", target, written, len(warnings))
        return IngestResult(dataset=self.DATASET, target=target, rows_written=written, warnings=warnings)

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
