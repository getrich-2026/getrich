"""华泰 INSIGHT raw parquet 读取适配器 + 代码归一化。

INSIGHT htsc_code 形如 ``600000.SH`` / ``000001.SZ``，与银河同构。
"""

from __future__ import annotations

import pandas as pd

from gr_data.common.parquet import read_parquet_if_exists
from gr_data.common.paths import RawPaths


PROVIDER = "insight"
SECURITY_TYPES = {"stock": "StockA", "etf": "FundETF", "index": "IndexCN"}
SUFFIX_TO_EXCHANGE = {"SH": "XSHG", "SZ": "XSHE"}


def split_htsc(code: str) -> tuple[str, str]:
    code = str(code).strip()
    if "." in code:
        _, suffix = code.rsplit(".", 1)
        return code, SUFFIX_TO_EXCHANGE.get(suffix.upper(), suffix.upper())
    return code, "UNKNOWN"


class InsightAdapter:
    def __init__(self, paths: RawPaths):
        self.paths = paths

    def read_basic_info(self, asset: str) -> pd.DataFrame | None:
        st = SECURITY_TYPES[asset]
        return read_parquet_if_exists(self.paths.dataset_file(PROVIDER, "basic_info", st))

    def read_trading_days(self, exchange: str) -> pd.DataFrame | None:
        return read_parquet_if_exists(self.paths.dataset_file(PROVIDER, "trading_days", exchange))

    def read_kline_day(self, code: str) -> pd.DataFrame | None:
        code_dir = self.paths.code_dir(PROVIDER, "kline_day", code)
        if not code_dir.exists():
            return None
        frames = [read_parquet_if_exists(f) for f in sorted(code_dir.glob("*.parquet"))]
        frames = [f for f in frames if f is not None and not f.empty]
        if not frames:
            return None
        out = pd.concat(frames, axis=0)
        return out[~out.index.duplicated(keep="last")].sort_index().reset_index()
