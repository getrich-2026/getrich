"""配置加载 - 统一从 config.yaml 读取.

config.yaml 只承载 "运行时开关":
    - AmazingData 连接信息
    - 存储路径
    - 日志
    - 限流
    - 每个 fetcher 的 enabled 开关

业务参数 (security_types / period / init_start_date / 切块大小)
全部硬编码在各 fetcher 类里, 不在 config.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class AmazingDataCfg:
    username: str
    password: str
    host: str
    port: int


@dataclass
class StorageCfg:
    data_dir: Path
    wipe_on_init: bool = False


@dataclass
class LoggingCfg:
    level: str = "INFO"
    file: str | None = None


@dataclass
class RateLimitCfg:
    sleep_between_requests_sec: float = 1.5
    max_retries: int = 5
    retry_backoff_base_sec: float = 3.0
    sleep_between_fetchers_sec: float = 5.0


@dataclass
class Config:
    amazing_data: AmazingDataCfg
    storage: StorageCfg
    logging: LoggingCfg
    rate_limit: RateLimitCfg
    # 全局起始日 (int8, 例 20240101); None 表示使用各 fetcher 自己的默认值
    start_date: int | None = None
    # 仅保留 enabled 开关: {fetcher_name: enabled}
    fetcher_enabled: dict[str, bool] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path = "config.yaml") -> "Config":
        path = Path(path)
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        ad = raw["amazing_data"]
        st = raw.get("storage", {}) or {}
        lg = raw.get("logging", {}) or {}
        rl = raw.get("rate_limit", {}) or {}

        fetcher_enabled: dict[str, bool] = {}
        for name, cfg in (raw.get("fetchers") or {}).items():
            # 支持两种写法:
            #   kline_day: true
            #   kline_day: { enabled: true }
            if isinstance(cfg, bool):
                fetcher_enabled[name] = cfg
            elif isinstance(cfg, dict):
                fetcher_enabled[name] = bool(cfg.get("enabled", True))
            elif cfg is None:
                fetcher_enabled[name] = True
            else:
                raise TypeError(
                    f"fetchers.{name}: unsupported value type {type(cfg).__name__}"
                )

        start_date_raw = raw.get("start_date")
        start_date: int | None = None
        if start_date_raw not in (None, "", "null"):
            start_date = int(start_date_raw)

        return cls(
            amazing_data=AmazingDataCfg(
                username=str(ad["username"]),
                password=str(ad["password"]),
                host=str(ad["host"]),
                port=int(ad["port"]),
            ),
            storage=StorageCfg(
                data_dir=Path(st.get("data_dir", "./data")).expanduser().resolve(),
                wipe_on_init=bool(st.get("wipe_on_init", False)),
            ),
            logging=LoggingCfg(
                level=lg.get("level", "INFO"),
                file=lg.get("file"),
            ),
            rate_limit=RateLimitCfg(
                sleep_between_requests_sec=float(rl.get("sleep_between_requests_sec", 1.5)),
                max_retries=int(rl.get("max_retries", 5)),
                retry_backoff_base_sec=float(rl.get("retry_backoff_base_sec", 3.0)),
                sleep_between_fetchers_sec=float(rl.get("sleep_between_fetchers_sec", 5.0)),
            ),
            start_date=start_date,
            fetcher_enabled=fetcher_enabled,
            raw=raw,
        )
