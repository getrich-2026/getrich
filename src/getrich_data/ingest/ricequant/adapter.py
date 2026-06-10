"""米筐 raw parquet 读取适配器 + 代码归一化。

米筐 order_book_id 形如 ``000001.XSHE`` / ``600000.XSHG``，exchange 已在后缀中。
canonical：symbol 保留 order_book_id，exchange 取后缀。
"""

from __future__ import annotations

import pandas as pd

from getrich_data.common.parquet import read_parquet_if_exists
from getrich_data.common.paths import RawPaths

PROVIDER = "ricequant"
ASSETS = ("stock", "etf", "index")

# 米筐交易所后缀已是 canonical（XSHG/XSHE/...），直接用
def split_obid(obid: str) -> tuple[str, str]:
    obid = str(obid).strip()
    if "." in obid:
        _, exch = obid.rsplit(".", 1)
        return obid, exch.upper()
    return obid, "UNKNOWN"


class RicequantAdapter:
    def __init__(self, paths: RawPaths):
        self.paths = paths

    def read_instruments(self, asset: str) -> pd.DataFrame | None:
        return read_parquet_if_exists(self.paths.dataset_file(PROVIDER, "instruments", asset))

    def read_calendar(self, market: str = "cn") -> pd.DataFrame | None:
        return read_parquet_if_exists(self.paths.dataset_file(PROVIDER, "calendar", market))

    def read_bars_1d(self, asset: str, code: str) -> pd.DataFrame | None:
        return read_parquet_if_exists(
            self.paths.dataset_file(PROVIDER, f"bars_1d/{asset}", code)
        )

    def list_bar_codes(self, asset: str) -> list[str]:
        d = self.paths.dataset_dir(PROVIDER, f"bars_1d/{asset}")
        if not d.exists():
            return []
        return [f.stem for f in sorted(d.glob("*.parquet"))]
