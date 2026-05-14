"""IncrementalFetcher - 增量父类.

读取本地 parquet 的最后一条时间, 只拉之后的数据并追加. 适用于:
  K线 (日线/分钟线) 等带时间轴的数据.

子类合约 (均为类常量/方法, 不依赖 config.yaml):
    NAME / INIT_START_DATE / CODE_CHUNK_SIZE / DATE_CHUNK_DAYS
    _iter_update_keys() / _last_local_date(key)
    _fetch_one(task)    / _save_chunk(task, result)
"""

from __future__ import annotations

from abc import ABC
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

from ...utils import chunk_date_range, chunk_list, today_int
from .base import BaseFetcher, FetchMode



class IncrementalFetcher(BaseFetcher, ABC):
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
    @property
    def _sync_status_path(self) -> Path:
        return self.data_dir / "_sync_status.json"

    def _pre_run(self, mode: FetchMode) -> None:
        super()._pre_run(mode)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if mode == FetchMode.INIT and self.cfg.storage.wipe_on_init:
            self._wipe()
            self.data_dir.mkdir(parents=True, exist_ok=True)
            
        self._sync_status: dict[str, dict[str, Any]] = {}
        if self._sync_status_path.exists():
            import json
            try:
                with open(self._sync_status_path, "r", encoding="utf-8") as f:
                    self._sync_status = json.load(f)
            except Exception as e:
                self.log.warning("Failed to load %s: %s", self._sync_status_path, e)

    def _post_run(self, mode: FetchMode) -> None:
        import json
        try:
            with open(self._sync_status_path, "w", encoding="utf-8") as f:
                json.dump(self._sync_status, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.log.error("Failed to save %s: %s", self._sync_status_path, e)
        super()._post_run(mode)

    def _post_fetch_hook(self, task: dict[str, Any], result: Any, error: Exception | None = None) -> None:
        import datetime
        now_str = datetime.datetime.now().isoformat()
        end_date = task.get("end_date")
        
        for code in task.get("code_chunk", []):
            k = str(code)
            st = self._sync_status.setdefault(k, {})
            
            if error:
                st["last_error"] = str(error)
                st["updated_at"] = now_str
            else:
                if end_date:
                    st["last_checked_date"] = max(st.get("last_checked_date") or 0, end_date)
                st["last_success_date"] = today_int()
                st["last_error"] = None
                st["updated_at"] = now_str

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
            last_data = self._last_local_date(k)
            st = self._sync_status.get(str(k), {})
            last_checked = st.get("last_checked_date")
            
            val_data = int(last_data) if last_data else 0
            val_checked = int(last_checked) if last_checked else 0
            
            # start = max(last_data_date, last_checked_date, floor - 1) + 1
            max_dt = max(val_data, val_checked, floor - 1)
            start = max_dt + 1
            
            # 同时把 last_data_date 记录进去，方便查阅
            if val_data:
                st["last_data_date"] = val_data
                
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
        self._loop_tasks(mode)
        self._post_run(mode)
        self.log.info("=== [%s] IncrementalFetcher done ===", self.NAME)

