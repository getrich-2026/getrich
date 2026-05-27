from __future__ import annotations

from functools import cached_property
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


class RawDataStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def calendar_paths(self) -> list[Path]:
        return sorted((self.data_dir / "calendar").glob("calendar_*.parquet"))

    def hist_code_path(self, security_type: str) -> Path:
        return self.data_dir / "hist_code_list" / f"hist_code_list_{security_type}.parquet"

    def hist_codes(self, security_type: str) -> list[str]:
        path = self.hist_code_path(security_type)
        if not path.exists():
            return []
        df = pd.read_parquet(path)
        if df.empty:
            return []
        values = df.iloc[:, 0].dropna().astype(str)
        return sorted(set(values.tolist()))

    def kline_day_paths(self) -> list[Path]:
        return sorted((self.data_dir / "kline_day").glob("*.parquet"))

    @cached_property
    def instrument_types(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for security_type, type_name in {
            "EXTRA_STOCK_A_SH_SZ": "stock",
            "EXTRA_ETF": "etf",
            "EXTRA_IDNEX_A_SH_SZ": "index",
        }.items():
            for code in self.hist_codes(security_type):
                mapping.setdefault(code, type_name)
        return mapping

    @cached_property
    def factor_file_by_code(self) -> dict[str, Path]:
        mapping: dict[str, Path] = {}
        for path in sorted((self.data_dir / "backward_factor").glob("*.parquet")):
            schema = pq.ParquetFile(path).schema_arrow
            for name in schema.names:
                if name != "date":
                    mapping.setdefault(name, path)
        return mapping

    def factor_series(self, code: str) -> pd.Series | None:
        path = self.factor_file_by_code.get(code)
        if path is None:
            return None
        df = pd.read_parquet(path, columns=[code])
        if df.empty:
            return None
        series = df[code].copy()
        series.index = pd.to_datetime(series.index).date
        series.name = "adj_factor"
        return series

