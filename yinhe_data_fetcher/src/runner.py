"""Runner - 读取 config, 构造 fetcher, 按注册顺序执行."""

from __future__ import annotations

from typing import Iterable

from .client import AmazingDataClient
from .config import Config
from .fetchers import BaseFetcher, FetchMode
from .logger import get_logger
from .registry import REGISTRY_CLASSES
from .utils import sleep_s


class Runner:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.log = get_logger("runner")
        self.client = AmazingDataClient(cfg.amazing_data)

    def _select(
        self, only: Iterable[str] | None
    ) -> list[type[BaseFetcher]]:
        only_set = set(only) if only else None
        enabled_map = self.cfg.fetcher_enabled
        selected: list[type[BaseFetcher]] = []

        # 按 REGISTRY_CLASSES 的声明顺序执行 (这是隐含的依赖顺序)
        for cls in REGISTRY_CLASSES:
            name = cls.NAME
            if only_set is not None:
                if name not in only_set:
                    continue
            else:
                enabled = enabled_map.get(name, False)
                if not enabled:
                    if name in enabled_map:
                        self.log.info("skip disabled fetcher: %s", name)
                    else:
                        self.log.debug("fetcher %s not in config, skip", name)
                    continue
            selected.append(cls)

        # 校验 --only 里传进来的名字都存在
        if only_set is not None:
            known = {c.NAME for c in REGISTRY_CLASSES}
            unknown = only_set - known
            if unknown:
                raise KeyError(
                    f"unknown fetcher names in --only: {sorted(unknown)}; "
                    f"known: {sorted(known)}"
                )

        return selected

    def run(self, mode: FetchMode, only: Iterable[str] | None = None) -> None:
        selected = self._select(only)
        if not selected:
            self.log.warning("no fetcher selected, nothing to do")
            return

        self.log.info(
            "run mode=%s, fetchers=%s", mode.value, [c.NAME for c in selected]
        )
        self.client.login()

        for i, cls in enumerate(selected):
            try:
                fetcher = cls(cfg=self.cfg, client=self.client)
                fetcher.run(mode)
            except Exception as e:  # noqa: BLE001
                self.log.exception("fetcher %s failed: %s", cls.NAME, e)

            if i < len(selected) - 1:
                sleep_s(self.cfg.rate_limit.sleep_between_fetchers_sec)

        self.log.info("all fetchers finished")
