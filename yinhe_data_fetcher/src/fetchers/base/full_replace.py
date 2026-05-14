"""FullReplaceFetcher - 全量覆盖父类.

每次 run 都会清空 data_dir 后重新抓, 适用于:
  交易日历 / 历史代码表 / 复权因子 ...
"""

from __future__ import annotations

from abc import ABC

from .base import BaseFetcher, FetchMode


class FullReplaceFetcher(BaseFetcher, ABC):
    TYPE = "full_replace"

    def run(self, mode: FetchMode) -> None:
        self.log.info(
            "=== [%s] FullReplaceFetcher start (mode=%s, dir=%s) ===",
            self.NAME,
            mode.value,
            self.data_dir,
        )
        self._pre_run(mode)
        self._wipe()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._loop_tasks(mode)
        self._post_run(mode)
        self.log.info("=== [%s] FullReplaceFetcher done ===", self.NAME)
