"""仅将 .BJ 行级失败转入待处理；共享文件与基础设施错误仍硬失败。"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Generator
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import numpy as np
import pandas as pd
import psycopg

from gr_data.common.ownership import OwnershipManager
from gr_data.common.quality import RowValidationError
from gr_data.db.copy import upsert_rows
from gr_data.ingest.base import BaseImporter
from gr_data.ingest.resolve import resolve_by_symbol_map
from gr_data.ingest.tushare.adapter import TushareAdapter


def raw_json(value: object) -> object:
    """保留源值，非有限值用文字表示，避免 JSONB 把 NaN／Inf 吞成 NULL。"""
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


class BJPendingImporter(BaseImporter):
    """共享严格 builder，仅对 BJ 定位行级错误后继续。

    正常批次按向量校验；残余失败按证券／日期组二分定位，避免全表逐行重建。
    严格试写在回滚保存点内验证真实 DDL；仅捕获行级错误及数据约束异常。
    峰值 O(单月源数据)，最差坏组二分有 O(g log g) 次组扫描。
    """

    BJ_SOURCE_DATASET = ""
    _tushare_adapter: TushareAdapter | None = None
    _bj_scope = False
    coverage: pd.DataFrame

    def _adapter(self) -> TushareAdapter:
        if self._tushare_adapter is None:
            self._tushare_adapter = TushareAdapter(self.paths, self.ctx.months)
        return self._tushare_adapter

    def _id_map(self) -> dict[str, int]:
        return resolve_by_symbol_map(self.conn, "tushare")

    def _build_strict(self) -> pd.DataFrame:
        raise NotImplementedError

    def _check_quality(self, df: pd.DataFrame) -> list[str]:
        if df.empty and getattr(self, "_bj_all_pending", False):
            return []  # 有源观察且全部是 BJ 待处理，不伪装成空响应。
        return super()._check_quality(df)

    def build(self) -> pd.DataFrame:
        if self.conn is None:  # 离线构建不能持久化待处理，保持严格校验。
            return self._build_strict()
        adapter = self._adapter()
        months = adapter.selected_months(self.BJ_SOURCE_DATASET)
        datasets = [self.BJ_SOURCE_DATASET]
        if self.BJ_SOURCE_DATASET == "daily":
            datasets += ["adj_factor", "stk_limit"]
        self._bj_sources: dict[tuple[str, str], pd.DataFrame] = {}
        for dataset in datasets:
            adapter.require_months(dataset, months)
            for month in months:
                frame = adapter.read_month(dataset, month)
                if frame is not None:
                    self._bj_sources[dataset, month] = frame
        primary = []
        partitions, offsets = [], []
        for month in months:
            frame = self._bj_sources.get((self.BJ_SOURCE_DATASET, month))
            if frame is not None:
                primary.append(frame)
                partitions += [month] * len(frame)
                offsets += list(range(len(frame)))
        if not primary:
            return self._build_strict()
        self._bj_raw = pd.concat(primary, ignore_index=True)
        self._bj_partitions = pd.Series(partitions, index=self._bj_raw.index, dtype="string")
        self._bj_offsets = offsets
        if "ts_code" not in self._bj_raw:
            return self._build_strict()  # 缺列是共享 schema 错误，不能转行级待处理。
        codes = self._bj_raw["ts_code"].astype("string").str.strip()
        bj = codes.str.endswith(".BJ", na=False)
        if not bj.any():
            with self._selection(self._bj_raw.index.tolist(), bj_only=False):
                return self._build_strict()
        self._bj_batch = self.ctx.batch_id or uuid4().hex
        if not self._bj_batch.strip() or len(self._bj_batch) > 128:
            raise ValueError("Invalid BJ pending batch_id")
        self._bj_failures: dict[int, tuple[list[str], str]] = {}
        # 先逐字段向量校验，避免坏重复行被严格 builder 的 keep-last 去重掩盖。
        self._primary_checks(self._bj_raw.loc[bj])
        non_bj = self._bj_raw.index[~bj].tolist()
        outputs = []
        if non_bj:
            with self._selection(non_bj, bj_only=False):
                outputs.append(self._build_strict())  # 沪深异常原样向上传播。
        remaining = [int(i) for i in self._bj_raw.index[bj] if i not in self._bj_failures]
        duplicate_keys = self._bj_raw.loc[remaining, ["ts_code", "trade_date"]].astype(str)
        duplicate_keys["ts_code"] = duplicate_keys["ts_code"].str.strip()
        duplicated = duplicate_keys.duplicated(keep=False)
        # 仅原始业务键重复的少数观察单独试验，不能让 keep-last 隐藏数据库约束失败。
        for i in duplicate_keys.index[duplicated]:
            self._locate([[int(i)]])
        remaining = [i for i in remaining if i not in self._bj_failures]
        mapping = self._id_map()
        groups: dict[tuple[object, str], list[int]] = {}
        for i in remaining:
            row = self._bj_raw.loc[i]
            key = (
                mapping.get(str(row["ts_code"]).strip(), str(row["ts_code"])),
                str(row["trade_date"]),
            )
            groups.setdefault(key, []).append(i)
        valid = self._locate(list(groups.values()))
        if valid:
            with self._selection(valid, bj_only=True):
                outputs.append(self._build_strict())
        if not outputs:
            with self._selection([], bj_only=True):
                self._build_strict()  # 停复牌覆盖等共享前置仍须通过。
        self._bj_all_pending = bool(self._bj_failures) and len(self._bj_failures) == len(
            self._bj_raw
        )
        self._persist_pending()
        result = (
            pd.concat(outputs, ignore_index=True)
            if outputs
            else pd.DataFrame(columns=list(self.contract.columns))
        )
        return result

    @contextmanager
    def _selection(self, indices: list[int], *, bj_only: bool) -> Generator[None, None, None]:
        previous = self._tushare_adapter
        previous_scope = self._bj_scope
        self._bj_scope = bj_only
        overrides = {}
        chosen = self._bj_raw.loc[indices]
        codes = set(chosen["ts_code"].astype(str).str.strip())
        for (dataset, month), frame in self._bj_sources.items():
            if dataset == self.BJ_SOURCE_DATASET:
                overrides[dataset, month] = chosen.loc[self._bj_partitions.loc[indices].eq(month)]
            elif "ts_code" in frame:
                symbols = frame["ts_code"].astype("string").str.strip()
                mask = symbols.isin(codes) if bj_only else ~symbols.str.endswith(".BJ", na=False)
                overrides[dataset, month] = frame.loc[mask]
        self._tushare_adapter = TushareAdapter(self.paths, self.ctx.months, overrides=overrides)
        try:
            yield
        finally:
            self._tushare_adapter = previous
            self._bj_scope = previous_scope

    def _locate(self, groups: list[list[int]]) -> list[int]:
        if not groups:
            return []
        indices = [i for group in groups for i in group]
        warnings = self.soft_warnings
        self.soft_warnings = []
        try:
            with self.conn.transaction(force_rollback=True), self._selection(indices, bj_only=True):
                frame = self._build_strict()
                problems = super()._check_quality(frame)
                if problems or self.soft_warnings:
                    raise RowValidationError("; ".join([*problems, *self.soft_warnings]))
                OwnershipManager(self.conn).check(self.contract.qualified, self.PROVIDER)
                upsert_rows(self.conn, self.contract, self._df_to_rows(frame))
        except (RowValidationError, psycopg.DataError, psycopg.IntegrityError) as exc:
            if len(groups) == 1:
                for i in indices:
                    self._bj_failures[i] = (["strict_record_validation"], str(exc)[:1500])
                return []
            middle = len(groups) // 2
            return self._locate(groups[:middle]) + self._locate(groups[middle:])
        finally:
            self.soft_warnings = warnings
        return indices

    def _primary_checks(self, frame: pd.DataFrame) -> None:
        required = {"ts_code", "trade_date"}
        numeric = []
        if self.BJ_SOURCE_DATASET == "daily":
            numeric = ["open", "high", "low", "close", "pre_close", "vol", "amount"]
        elif self.BJ_SOURCE_DATASET == "adj_factor":
            numeric = ["adj_factor"]
        elif self.BJ_SOURCE_DATASET == "daily_basic":
            numeric = [
                c
                for c in self.contract.columns
                if c not in {"instrument_id", "trading_day", "source", "currency", "available_at"}
            ]
        else:
            required |= {"suspend_type", "suspend_timing"}
        required |= set(numeric)
        if required - set(frame.columns):
            raise ValueError(
                f"{self.BJ_SOURCE_DATASET}: missing required fields "
                f"{sorted(required - set(frame.columns))}"
            )
        checks: list[tuple[str, pd.Series]] = []
        dates = pd.to_datetime(frame["trade_date"].astype(str), format="%Y%m%d", errors="coerce")
        if self.ctx.requested_days is not None:
            checks.append(
                (
                    "outside_requested_days",
                    dates.notna() & ~dates.dt.date.isin(self.ctx.requested_days),
                )
            )
        checks += [
            ("invalid_trade_date", dates.isna()),
            (
                "outside_raw_partition",
                dates.notna() & dates.dt.strftime("%Y-%m").ne(self._bj_partitions.loc[frame.index]),
            ),
        ]
        checks.append(
            ("unknown_symbol", frame["ts_code"].astype(str).str.strip().map(self._id_map()).isna())
        )
        values = {c: pd.to_numeric(frame[c], errors="coerce") for c in numeric}
        for column, value in values.items():
            nullable = self.BJ_SOURCE_DATASET == "daily_basic" or column == "pre_close"
            present = frame[column].notna() if nullable else pd.Series(True, index=frame.index)
            checks.append((f"invalid_numeric_{column}", present & ~np.isfinite(value)))
            if self.BJ_SOURCE_DATASET in {"daily", "adj_factor"}:
                bad = value.lt(0) if column in {"vol", "amount"} else value.le(0)
                checks.append((f"invalid_range_{column}", present & bad))
        if self.BJ_SOURCE_DATASET == "daily":
            checks.append(
                (
                    "volume_bigint_capacity",
                    values["vol"].astype(float).mul(100).round().ge(float(2**63)),
                )
            )
            checks.append(
                (
                    "invalid_ohlc_range",
                    values["high"].lt(values["low"])
                    | values["open"].lt(values["low"])
                    | values["open"].gt(values["high"])
                    | values["close"].lt(values["low"])
                    | values["close"].gt(values["high"]),
                )
            )
            adj = pd.concat(
                [f for (dataset, _), f in self._bj_sources.items() if dataset == "adj_factor"],
                ignore_index=True,
            )
            if not {"ts_code", "trade_date", "adj_factor"} <= set(adj.columns):
                raise ValueError("adj_factor missing required fields")
            adj = adj.assign(
                _code=adj["ts_code"].astype(str).str.strip(),
                _day=pd.to_datetime(
                    adj["trade_date"].astype(str), format="%Y%m%d", errors="coerce"
                ),
            )
            adj = adj.drop_duplicates(["_code", "_day"], keep="last").set_index(["_code", "_day"])
            factors = pd.to_numeric(adj["adj_factor"], errors="coerce").reindex(
                pd.MultiIndex.from_arrays([frame["ts_code"].astype(str).str.strip(), dates])
            )
            factors = pd.Series(factors.to_numpy(), index=frame.index)
            finite = pd.Series(np.isfinite(factors.to_numpy(dtype=float)), index=frame.index)
            checks.append(("missing_or_invalid_adj_factor", ~finite | factors.le(0)))
        elif self.BJ_SOURCE_DATASET == "daily_basic":
            checks.append(
                (
                    "invalid_limit_status",
                    frame["limit_status"].notna() & ~values["limit_status"].isin(range(7)),
                )
            )
        elif self.BJ_SOURCE_DATASET == "suspend_d":
            checks.append(("invalid_suspend_type", ~frame["suspend_type"].isin(["S", "R"])))
        for rule, mask in checks:
            for i in frame.index[mask]:
                rules, _ = self._bj_failures.setdefault(
                    int(i), ([], "BJ source record validation failed")
                )
                rules.append(rule)

    def _persist_pending(self) -> None:
        if not self._bj_failures:
            return
        OwnershipManager(self.conn).claim(
            "ops.tushare_bj_pending", "tushare", channel=self.ctx.channel
        )
        records = []
        for i, (rules, detail) in self._bj_failures.items():
            row = self._bj_raw.loc[i].to_dict()
            partition = str(self._bj_partitions.loc[i])
            original = {"primary": raw_json(row)}
            if self.BJ_SOURCE_DATASET == "daily":
                auxiliary = {}
                for dataset in ("adj_factor", "stk_limit"):
                    raw = self._bj_sources[dataset, partition]
                    selected = raw.loc[
                        raw["ts_code"].astype(str).str.strip().eq(str(row["ts_code"]).strip())
                        & raw["trade_date"].astype(str).eq(str(row["trade_date"]))
                    ]
                    auxiliary[dataset] = raw_json(selected.to_dict("records"))
                original["auxiliary"] = auxiliary
            encoded = json.dumps(original, ensure_ascii=False, sort_keys=True, allow_nan=False)
            fingerprint = hashlib.sha256(
                f"{partition}:{self._bj_offsets[i]}:{encoded}".encode()
            ).hexdigest()
            parsed = pd.to_datetime(str(row["trade_date"]), format="%Y%m%d", errors="coerce")
            records.append(
                (
                    "tushare",
                    self.DATASET,
                    self.BJ_SOURCE_DATASET,
                    str(row["ts_code"]).strip(),
                    str(row["trade_date"]),
                    None if pd.isna(parsed) else parsed.date(),
                    partition,
                    self._bj_batch,
                    fingerprint,
                    self._bj_offsets[i],
                    rules,
                    detail,
                    encoded,
                )
            )
        with self.conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO ops.tushare_bj_pending "
                "(source,dataset,source_dataset,source_code,source_date,trading_day,"
                "raw_partition,batch_id,record_fingerprint,raw_row_index,failure_rules,"
                "failure_detail,raw_values) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (source,dataset,batch_id,record_fingerprint) DO UPDATE "
                "SET failure_rules=EXCLUDED.failure_rules,"
                "failure_detail=EXCLUDED.failure_detail,updated_at=now()",
                records,
            )
        self.log.info(
            "BJ records pending dataset=%s rows=%d codes=%d batch=%s",
            self.DATASET,
            len(records),
            len({r[3] for r in records}),
            self._bj_batch,
        )
