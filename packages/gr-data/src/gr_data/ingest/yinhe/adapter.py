"""银河 raw parquet 读取适配器。

把 $RAW_PARQUET_ROOT/yinhe/ 下的 parquet 读成 DataFrame，供 transform 使用。
不做归一化，只负责定位与读取。
"""

from __future__ import annotations

import re

import pandas as pd

from gr_data.common.parquet import read_parquet_if_exists
from gr_data.common.paths import RawPaths


PROVIDER = "yinhe"
SECURITY_TYPES = {
    "stock": "EXTRA_STOCK_A_SH_SZ",
    "etf": "EXTRA_ETF",
    "index": "EXTRA_IDNEX_A_SH_SZ",
}


class YinheAdapter:
    def __init__(self, paths: RawPaths):
        self.paths = paths

    def read_calendar(self, market: str = "SH") -> pd.DataFrame | None:
        df = read_parquet_if_exists(
            self.paths.dataset_file(PROVIDER, "calendar", f"calendar_{market}")
        )
        return df.reset_index() if df is not None else None

    def read_code_list(self, asset: str) -> list[str]:
        st = SECURITY_TYPES[asset]
        df = read_parquet_if_exists(self.paths.dataset_file(PROVIDER, "hist_code_list", st))
        if df is None or df.empty or "code" not in df.columns:
            return []
        return [str(c) for c in df["code"].tolist()]

    def read_kline_day(self, code: str) -> pd.DataFrame | None:
        files = self.paths.code_month_files(PROVIDER, "kline_day", code)
        frames = [read_parquet_if_exists(f) for f in files]
        frames = [f for f in frames if f is not None and not f.empty]
        if not frames:
            return None
        out = pd.concat(frames, axis=0)
        return out[~out.index.duplicated(keep="last")].sort_index().reset_index()

    def read_backward_factor(self, asset: str) -> pd.DataFrame | None:
        """读取指定资产类型的复权因子（宽表）。

        银河复权因子为逐日宽表：index=日期，columns=证券代码，value=后复权因子。
        raw 层按 chunk 分文件落盘（每文件约 200 列），此处横向合并所有 chunk。

        Returns:
            DataFrame: index=日期(DatetimeIndex)，columns=证券代码，或 None。
        """
        st = SECURITY_TYPES.get(asset)
        if st is None:
            return None
        # 只认 <st>_chunk<NNNN>.parquet；旧版原子写残留的 *.tmp-<hex>.parquet 也会被 glob 命中。
        chunk_re = re.compile(rf"{re.escape(st)}_chunk\d{{4}}\.parquet")
        factor_dir = self.paths.dataset_dir(PROVIDER, "backward_factor")
        chunk_files = sorted(
            f for f in factor_dir.glob(f"{st}_chunk*.parquet") if chunk_re.fullmatch(f.name)
        )
        frames = [read_parquet_if_exists(f) for f in chunk_files]
        frames = [f for f in frames if f is not None and not f.empty]
        if not frames:
            return None
        # 各 chunk 共享 date 索引，横向拼接（列=证券代码）。
        frames = [f.set_index("date") if "date" in f.columns else f for f in frames]
        wide = pd.concat(frames, axis=1)
        wide.index = pd.to_datetime(wide.index)
        return wide.loc[:, ~wide.columns.duplicated()]
