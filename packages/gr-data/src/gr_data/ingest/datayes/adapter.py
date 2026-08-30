"""读 datayes raw parquet（只读，不归一化）。"""

from __future__ import annotations

import pandas as pd

from gr_data.common.parquet import read_parquet_if_exists
from gr_data.common.paths import RawPaths


PROVIDER = "datayes"


class DatayesAdapter:
    def __init__(self, paths: RawPaths):
        self.paths = paths

    def list_months(self, dataset: str) -> list[str]:
        d = self.paths.dataset_dir(PROVIDER, dataset)
        if not d.exists():
            return []
        return sorted(p.stem for p in d.glob("*.parquet"))

    def read_month(self, dataset: str, ym: str) -> pd.DataFrame | None:
        return read_parquet_if_exists(self.paths.dataset_file(PROVIDER, dataset, ym))

    def read_all_months(self, dataset: str) -> pd.DataFrame:
        frames = [self.read_month(dataset, ym) for ym in self.list_months(dataset)]
        frames = [f for f in frames if f is not None and not f.empty]
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, axis=0, ignore_index=True)
