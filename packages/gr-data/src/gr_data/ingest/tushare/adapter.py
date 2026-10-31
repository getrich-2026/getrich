"""Tushare raw parquet 读取适配器。

只负责「把 raw 层落盘的文件读回来」，不做归一化——归一化在 importers 里。
逐日数据集按自然月分区，因此读取时需要把所有月份拼起来。

读取一律严格：文件存在但不可读抛 ``CorruptRawError``，不当作缺失；
只认 ``YYYY-MM.parquet`` 分区名，原子写残留的 ``*.tmp-*`` 文件不当数据读入。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping

import pandas as pd

from gr_data.common.parquet import read_parquet_strict
from gr_data.common.paths import RawPaths
from gr_data.ingest.base import IngestGateError


log = logging.getLogger(__name__)

PROVIDER = "tushare"

ASSETS = ("stock", "index", "future")
CALENDAR_EXCHANGES = ("SSE", "SZSE")

# Tushare trade_cal 的 exchange 取值 → canonical 交易所码
CALENDAR_EXCHANGE_MAP = {"SSE": "XSHG", "SZSE": "XSHE"}

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


class TushareAdapter:
    def __init__(
        self,
        paths: RawPaths,
        months: tuple[str, ...] | None = None,
        *,
        overrides: Mapping[tuple[str, str], pd.DataFrame] | None = None,
    ):
        self.paths = paths
        # None = 全部月份（默认，与以前一致）；给了就只读这些月，见
        # IngestContext.months 里关于内存的说明。
        self.months = months
        #: 软告警（如残留临时文件），由 importer 汇总进运行结果。
        self.notices: list[str] = []
        self._overrides = overrides or {}

    def read_instruments(self, asset: str) -> pd.DataFrame | None:
        return read_parquet_strict(self.paths.dataset_file(PROVIDER, "instruments", asset))

    def read_calendar(self, exchange: str) -> pd.DataFrame | None:
        return read_parquet_strict(self.paths.dataset_file(PROVIDER, "calendar", exchange))

    def list_months(self, dataset: str) -> list[str]:
        d = self.paths.dataset_dir(PROVIDER, dataset)
        if not d.exists():
            return []
        stems = sorted(f.stem for f in d.glob("*.parquet"))
        stray = [s for s in stems if not _MONTH_RE.match(s)]
        for name in stray:
            notice = f"{dataset}: ignored non-partition file {name}.parquet"
            if notice not in self.notices:
                self.notices.append(notice)
                log.warning("Ignored stray raw file dataset=%s file=%s.parquet", dataset, name)
        found = [s for s in stems if _MONTH_RE.match(s)]
        return [m for m in found if m in self.months] if self.months else found

    def require_months(self, dataset: str, months: list[str] | tuple[str, ...]) -> None:
        """请求的月份必须都有分区；缺任何一个即硬失败，不把缺分区当作无数据。"""
        if not months:
            raise IngestGateError(f"{dataset}: no raw partitions selected")
        present = set(self.list_months(dataset))
        missing = [m for m in months if m not in present]
        if missing:
            raise IngestGateError(f"{dataset}: missing raw partitions {missing}")

    def selected_months(self, dataset: str) -> list[str]:
        """本次应处理的月份：指定了 months 就用它，否则取该数据集现有的全部分区。"""
        months = list(self.months) if self.months else self.list_months(dataset)
        self.require_months(dataset, months)
        return months

    def read_month(self, dataset: str, ym: str) -> pd.DataFrame | None:
        if (dataset, ym) in self._overrides:
            return self._overrides[dataset, ym].copy()
        return read_parquet_strict(self.paths.dataset_file(PROVIDER, dataset, ym))

    def read_all_months(self, dataset: str) -> pd.DataFrame:
        """把某个按月分区的数据集全部读回并纵向拼接。缺失时返回空表。"""
        frames = []
        for ym in self.list_months(dataset):
            df = self.read_month(dataset, ym)
            if df is not None and not df.empty:
                frames.append(df)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, axis=0, ignore_index=True)
