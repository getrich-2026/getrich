from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Literal

import pandas as pd
from sqlalchemy import Engine

from .config import ImportConfig
from .db import delete_all, max_value, target_empty, upsert_dataframe
from .raw_store import RawDataStore


ImportMode = Literal["auto", "full", "incremental"]
ResolvedMode = Literal["full", "incremental"]


@dataclass
class ImportResult:
    name: str
    table: str
    mode: ResolvedMode
    rows: int = 0


@dataclass
class ImportContext:
    config: ImportConfig
    engine: Engine
    store: RawDataStore
    dry_run: bool = False


class BaseImporter:
    name: str = ""
    target_table: str = ""
    primary_keys: tuple[str, ...] = ()
    watermark_column: str | None = None
    full_replace: bool = False
    delete_before_full: bool = True

    def decide_mode(self, ctx: ImportContext, requested: ImportMode) -> ResolvedMode:
        if self.full_replace:
            return "full"
        if requested == "full":
            return "full"
        if requested == "incremental":
            return "incremental"
        with ctx.engine.begin() as conn:
            if target_empty(conn, self.target_table):
                return "full"
        return "incremental"

    def latest_watermark(self, ctx: ImportContext) -> object | None:
        if not self.watermark_column:
            return None
        with ctx.engine.begin() as conn:
            return max_value(conn, self.target_table, self.watermark_column)

    def stream_frames(
        self, ctx: ImportContext, mode: ResolvedMode, since: object | None
    ) -> Iterator[pd.DataFrame]:
        raise NotImplementedError

    def run(self, ctx: ImportContext, requested: ImportMode = "auto") -> ImportResult:
        mode = self.decide_mode(ctx, requested)
        since = None if mode == "full" else self.latest_watermark(ctx)
        rows = 0
        if ctx.dry_run:
            for df in self.stream_frames(ctx, mode, since):
                rows += len(df)
            return ImportResult(self.name, self.target_table, mode, rows)

        with ctx.engine.begin() as conn:
            if mode == "full" and self.delete_before_full:
                delete_all(conn, self.target_table)
            for df in self.stream_frames(ctx, mode, since):
                rows += upsert_dataframe(
                    conn,
                    df,
                    self.target_table,
                    self.primary_keys,
                    ctx.config.batch_rows,
                )
        return ImportResult(self.name, self.target_table, mode, rows)
