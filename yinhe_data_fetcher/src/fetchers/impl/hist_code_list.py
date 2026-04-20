"""历史代码表 - FullReplace."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Iterator

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

    def _iter_tasks(self, mode) -> Iterator[dict[str, Any]]:
        end = today_int()
        start = self._effective_start(self.START_DATE)
        for st in self.SECURITY_TYPES:
            yield {
                "security_type": st,
                "start_date": start,
                "end_date": end,
                "label": f"hist_code_list {st} [{start},{end}]",
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
        if not isinstance(result, pd.DataFrame):
            try:
                result = pd.DataFrame(result)
            except Exception:
                self.log.error("unexpected hist_code_list return type %s", type(result))
                return
        df = result.copy()
        if df.index.name is None:
            df.index.name = "row"
        out = self.data_dir / f"hist_code_list_{st}.parquet"
        write_parquet(df, out, append=False)
        self.log.info("write %s (%d rows)", out, len(df))
