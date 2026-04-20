"""BaseFetcher - 所有 fetcher 的抽象父类.

提供: 初始化, 切块/重试/限流循环, 通用 _is_empty 判空.
不直接被使用, 业务代码应继承 FullReplaceFetcher / IncrementalFetcher.
"""

from __future__ import annotations

import enum
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, Iterator

import pandas as pd

from ...client import AmazingDataClient
from ...config import Config, RateLimitCfg
from ...logger import get_logger
from ...utils import retry_call, sleep_s


class FetchMode(str, enum.Enum):
    INIT = "init"      # 全量初始化
    UPDATE = "update"  # 每日增量


class BaseFetcher(ABC):
    """Fetcher 的最顶层抽象父类."""

    # ---- 必须被子类覆盖 ----------------------------------------------
    NAME: ClassVar[str] = ""              # data/ 下的子目录名 & registry key
    TYPE: ClassVar[str] = "base"          # full_replace | incremental

    # ---- 可选的默认切块参数 (子类按需覆盖) ---------------------------
    CODE_CHUNK_SIZE: ClassVar[int] = 50
    DATE_CHUNK_DAYS: ClassVar[int] = 60

    def __init__(self, cfg: Config, client: AmazingDataClient):
        if not self.NAME:
            raise ValueError(f"{type(self).__name__}.NAME must be set")
        self.cfg = cfg
        self.client = client
        self.rate: RateLimitCfg = cfg.rate_limit
        self.data_dir: Path = cfg.storage.data_dir / self.NAME
        self.log = get_logger(f"fetcher.{self.NAME}")

    @property
    def name(self) -> str:
        return self.NAME

    # ------------------------------------------------------------------
    # 子类必须实现
    # ------------------------------------------------------------------
    @abstractmethod
    def _iter_tasks(self, mode: FetchMode) -> Iterator[dict[str, Any]]:
        """产出一批 "任务", 每个任务是一次 API 调用所需的参数."""

    @abstractmethod
    def _fetch_one(self, task: dict[str, Any]) -> Any:
        """根据 task 调用 AmazingData 接口, 返回原始结果."""

    @abstractmethod
    def _save_chunk(self, task: dict[str, Any], result: Any) -> None:
        """把一次请求的结果落盘 (parquet); 分文件策略由子类决定."""

    @abstractmethod
    def run(self, mode: FetchMode) -> None: ...

    # ------------------------------------------------------------------
    # 可选钩子
    # ------------------------------------------------------------------
    def _pre_run(self, mode: FetchMode) -> None:
        """run 开始时触发, 子类可在这里做一次性准备."""

    def _post_run(self, mode: FetchMode) -> None:
        """run 结束时触发."""

    # ------------------------------------------------------------------
    # 通用逻辑
    # ------------------------------------------------------------------
    def _call_with_retry(self, task: dict[str, Any]) -> Any:
        return retry_call(
            self._fetch_one,
            task,
            max_retries=self.rate.max_retries,
            backoff_base=self.rate.retry_backoff_base_sec,
            logger=self.log,
        )

    def _wipe(self) -> None:
        if self.data_dir.exists():
            self.log.warning("wipe existing dir %s", self.data_dir)
            shutil.rmtree(self.data_dir)

    @property
    def calendar(self) -> list[int]:
        return self.client.calendar

    def _effective_start(self, default_start: int) -> int:
        """应用全局 config.start_date 裁剪 -> 取 max(default, cfg.start_date).

        任何 fetcher 如果需要 "起始日期" 都应通过此函数拿, 保证:
        - 类里的 INIT_START_DATE / START_DATE 是 "自然下限"
        - config.yaml 的 start_date 是 "用户进一步收紧的下限"
        """
        floor = self.cfg.start_date
        if floor is None:
            return int(default_start)
        return max(int(default_start), int(floor))

    def _loop_tasks(self, mode: FetchMode) -> None:
        """串联 _iter_tasks -> _fetch_one -> _save_chunk, 含 sleep/retry."""
        n_done = 0
        n_fail = 0
        for task in self._iter_tasks(mode):
            label = task.get("label") or task
            self.log.info("[%s] fetch %s", self.NAME, label)
            try:
                result = self._call_with_retry(task)
            except Exception as e:  # noqa: BLE001
                n_fail += 1
                self.log.error("[%s] task failed permanently: %s (%s)", self.NAME, label, e)
                sleep_s(self.rate.sleep_between_requests_sec)
                continue

            if self._is_empty(result):
                self.log.info("[%s] empty result, skip %s", self.NAME, label)
            else:
                self._save_chunk(task, result)
                n_done += 1
            sleep_s(self.rate.sleep_between_requests_sec)

        self.log.info("[%s] done: %d chunks written, %d failed", self.NAME, n_done, n_fail)

    @staticmethod
    def _is_empty(result: Any) -> bool:
        if result is None:
            return True
        if isinstance(result, pd.DataFrame):
            return result.empty
        if isinstance(result, dict):
            return len(result) == 0 or all(
                (isinstance(v, pd.DataFrame) and v.empty) or v is None
                for v in result.values()
            )
        if hasattr(result, "__len__"):
            try:
                return len(result) == 0
            except TypeError:
                return False
        return False
