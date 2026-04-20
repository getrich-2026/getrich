"""IncrementalFetcher - 增量父类.

读取本地 parquet 的最后一条时间, 只拉之后的数据并追加. 适用于:
  K线 (日线/分钟线) 等带时间轴的数据.

子类合约 (均为类常量/方法, 不依赖 config.yaml):
    NAME / INIT_START_DATE / CODE_CHUNK_SIZE / DATE_CHUNK_DAYS
    _iter_update_keys() / _last_local_date(key)
    _fetch_one(task)    / _save_chunk(task, result)
"""

from __future__ import annotations

from typing import Any, ClassVar, Iterator

from ...utils import chunk_date_range, chunk_list, today_int
from .base import BaseFetcher, FetchMode


class IncrementalFetcher(BaseFetcher):
    TYPE = "incremental"

    # 子类覆盖: init 模式下的起点 (int8 date)
    INIT_START_DATE: ClassVar[int] = 20130101

    # ------------------------------------------------------------------
    # 子类必须实现
    # ------------------------------------------------------------------
    def _iter_update_keys(self) -> list[Any]:
        """本次需要更新的所有 "key" (例: 所有股票 code)."""
        raise NotImplementedError

    def _last_local_date(self, key: Any) -> int | None:
        """该 key 本地 parquet 的最后日期; 无数据返回 None."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 可覆盖
    # ------------------------------------------------------------------
    def _end_date(self) -> int:
        return today_int()

    def _iter_tasks_for_range(
        self,
        keys: list[Any],
        begin_date: int,
        end_date: int,
    ) -> Iterator[dict[str, Any]]:
        """默认按 (CODE_CHUNK_SIZE x DATE_CHUNK_DAYS) 切块, 子类可覆盖."""
        for code_chunk in chunk_list(keys, self.CODE_CHUNK_SIZE):
            for s, e in chunk_date_range(begin_date, end_date, self.DATE_CHUNK_DAYS):
                yield {
                    "code_chunk": list(code_chunk),
                    "begin_date": s,
                    "end_date": e,
                    "label": f"{len(code_chunk)} codes [{s},{e}]",
                }

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def _iter_tasks(self, mode: FetchMode) -> Iterator[dict[str, Any]]:
        end = self._end_date()
        # 应用全局 start_date 下限
        floor = self._effective_start(self.INIT_START_DATE)

        if mode == FetchMode.INIT:
            keys = self._iter_update_keys()
            self.log.info(
                "[%s] INIT: %d keys, range [%s, %s]", self.NAME, len(keys), floor, end
            )
            yield from self._iter_tasks_for_range(keys, floor, end)
            return

        # UPDATE: 按 key 分组, 起点相同的合并
        all_keys = self._iter_update_keys()
        groups: dict[int, list[Any]] = {}
        for k in all_keys:
            last = self._last_local_date(k)
            start = floor if last is None else max(int(last) + 1, floor)
            if start > end:
                continue
            groups.setdefault(start, []).append(k)

        if not groups:
            self.log.info("[%s] UPDATE: nothing to do (all up-to-date)", self.NAME)
            return

        self.log.info(
            "[%s] UPDATE: end=%s, groups=%s",
            self.NAME,
            end,
            {s: len(v) for s, v in sorted(groups.items())},
        )
        for start, keys in sorted(groups.items()):
            yield from self._iter_tasks_for_range(keys, start, end)

    def run(self, mode: FetchMode) -> None:
        self.log.info(
            "=== [%s] IncrementalFetcher start (mode=%s, dir=%s) ===",
            self.NAME,
            mode.value,
            self.data_dir,
        )
        self._pre_run(mode)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if mode == FetchMode.INIT and self.cfg.storage.wipe_on_init:
            self._wipe()
            self.data_dir.mkdir(parents=True, exist_ok=True)
        self._loop_tasks(mode)
        self._post_run(mode)
        self.log.info("=== [%s] IncrementalFetcher done ===", self.NAME)
