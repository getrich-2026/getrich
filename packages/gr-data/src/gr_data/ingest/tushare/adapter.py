"""Tushare raw parquet 读取适配器。

只负责「把 raw 层落盘的文件读回来」，不做归一化——归一化在 importers 里。
逐日数据集按自然月分区，因此读取时需要把所有月份拼起来。
"""

from __future__ import annotations

import pandas as pd

from gr_data.common.parquet import read_parquet_if_exists
from gr_data.common.paths import RawPaths


PROVIDER = "tushare"

ASSETS = ("stock", "index", "future")
CALENDAR_EXCHANGES = ("SSE", "SZSE")

# Tushare trade_cal 的 exchange 取值 → canonical 交易所码
CALENDAR_EXCHANGE_MAP = {"SSE": "XSHG", "SZSE": "XSHE"}


class TushareAdapter:
    def __init__(self, paths: RawPaths):
        self.paths = paths

    def read_instruments(self, asset: str) -> pd.DataFrame | None:
        return read_parquet_if_exists(self.paths.dataset_file(PROVIDER, "instruments", asset))

    def read_calendar(self, exchange: str) -> pd.DataFrame | None:
        return read_parquet_if_exists(self.paths.dataset_file(PROVIDER, "calendar", exchange))

    def list_months(self, dataset: str) -> list[str]:
        d = self.paths.dataset_dir(PROVIDER, dataset)
        if not d.exists():
            return []
        return sorted(f.stem for f in d.glob("*.parquet"))

    def read_month(self, dataset: str, ym: str) -> pd.DataFrame | None:
        return read_parquet_if_exists(self.paths.dataset_file(PROVIDER, dataset, ym))

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
