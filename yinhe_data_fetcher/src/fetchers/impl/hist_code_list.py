"""历史代码表 - FullReplace."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd

from ...utils import today_int, write_parquet
from ..base import FullReplaceFetcher


class HistCodeListFetcher(FullReplaceFetcher):
    """按 security_type 抓取 [START_DATE, today] 的历史代码表."""

    NAME = "hist_code_list"

    SECURITY_TYPES: ClassVar[list[str]] = [
        "EXTRA_STOCK_A_SH_SZ",
        "EXTRA_ETF",
        "EXTRA_IDNEX_A_SH_SZ",
    ]
    START_DATE: ClassVar[int] = 20130101

    def _pre_run(self, mode) -> None:
        super()._pre_run(mode)
        self.accumulated: dict[str, set[str]] = {st: set() for st in self.SECURITY_TYPES}

    def _iter_tasks(self, mode) -> Iterator[dict[str, Any]]:
        end = today_int()
        start = self._effective_start(self.START_DATE)
        
        start_year = start // 10000
        end_year = end // 10000
        
        for st in self.SECURITY_TYPES:
            for y in range(start_year, end_year + 1):
                start_dt = max(start, y * 10000 + 101)
                end_dt = min(end, y * 10000 + 1231)
                if start_dt > end_dt:
                    continue
                yield {
                    "security_type": st,
                    "start_date": start_dt,
                    "end_date": end_dt,
                    "label": f"hist_code_list {st} [{start_dt},{end_dt}]",
                }

    def _fetch_one(self, task: dict[str, Any]) -> Any:
        sdk_cache = Path(self.cfg.storage.data_dir) / "_sdk_cache" / self.NAME
        sdk_cache.mkdir(parents=True, exist_ok=True)
        return self.client.base_data.get_hist_code_list(
            security_type=task["security_type"],
            start_date=task["start_date"],
            end_date=task["end_date"],
            local_path=str(sdk_cache) + "/",
        )

    def _save_chunk(self, task: dict[str, Any], result: Any) -> None:
        st = task["security_type"]
        if result:
            self.accumulated[st].update(result)

    def _post_run(self, mode) -> None:
        for st, codes in self.accumulated.items():
            sorted_codes = sorted(list(codes))
            df = pd.DataFrame(sorted_codes)
            if df.index.name is None:
                df.index.name = "row"
            out = self.data_dir / f"hist_code_list_{st}.parquet"
            write_parquet(df, out, append=False)
            self.log.info("write %s (%d rows)", out, len(df))
        super()._post_run(mode)

