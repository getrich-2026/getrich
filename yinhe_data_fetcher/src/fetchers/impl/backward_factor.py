"""复权因子 - FullReplace."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd

from ...utils import chunk_list, sleep_s, write_parquet
from ..base import FullReplaceFetcher


class BackwardFactorFetcher(FullReplaceFetcher):
    NAME = "backward_factor"

    SECURITY_TYPES: ClassVar[list[str]] = ["EXTRA_STOCK_A", "EXTRA_ETF"]
    CODE_CHUNK_SIZE = 100

    def _wipe(self) -> None:
        # Do not wipe during resumption to preserve already downloaded chunks.
        pass

    def _iter_tasks(self, mode) -> Iterator[dict[str, Any]]:
        for st in self.SECURITY_TYPES:
            self.log.info("[%s] list codes for %s", self.NAME, st)
            code_list = self.client.base_data.get_code_list(security_type=st)
            code_list = sorted([str(c) for c in list(code_list)])
            for i, chunk in enumerate(chunk_list(code_list, self.CODE_CHUNK_SIZE)):
                out = self.data_dir / f"backward_factor_{st}_chunk{i:04d}.parquet"
                if out.exists():
                    self.log.info("[%s] skip existing chunk#%d for %s", self.NAME, i, st)
                    continue
                yield {
                    "security_type": st,
                    "chunk_idx": i,
                    "code_chunk": chunk,
                    "label": f"backward_factor {st} chunk#{i} n={len(chunk)}",
                }
            sleep_s(self.rate.sleep_between_requests_sec)

    def _fetch_one(self, task: dict[str, Any]) -> Any:
        sdk_cache = Path(self.cfg.storage.data_dir) / "_sdk_cache" / self.NAME
        sdk_cache.mkdir(parents=True, exist_ok=True)
        return self.client.base_data.get_backward_factor(
            task["code_chunk"],
            local_path=str(sdk_cache) + "/",
            is_local=False,
        )

    def _save_chunk(self, task: dict[str, Any], result: Any) -> None:
        st = task["security_type"]
        idx = task["chunk_idx"]
        if not isinstance(result, pd.DataFrame):
            try:
                result = pd.DataFrame(result)
            except Exception:
                self.log.error(
                    "unexpected backward_factor return type %s", type(result)
                )
                return
        df = result.copy()
        if df.index.name is None:
            df.index.name = "date"
        out = self.data_dir / f"backward_factor_{st}_chunk{idx:04d}.parquet"
        write_parquet(df, out, append=False)
        self.log.info("write %s (shape=%s)", out, df.shape)
