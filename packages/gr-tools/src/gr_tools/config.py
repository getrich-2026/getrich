"""无业务依赖的公共配置模型；不加载 dotenv 或创建全局单例。"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_LOG_FORMAT = "[%(asctime)s][%(name)s][%(levelname)s][%(request_id)s] %(message)s"


@dataclass(frozen=True)
class LoggingConfig:
    """进程日志选项。环境加载由应用入口选择时机。"""

    level: str = "INFO"
    format: str = DEFAULT_LOG_FORMAT
    file_path: Path | None = None
    json_format: bool = False

    @classmethod
    def from_env(cls, project_root: Path) -> LoggingConfig:
        """读取 LOG_*；相对输出路径以调用方提供的根目录解析。"""
        level = os.environ.get("LOG_LEVEL", "INFO").upper()
        if not isinstance(logging.getLevelName(level), int):
            raise ValueError("LOG_LEVEL must be a standard logging level")
        raw_json = os.environ.get("LOG_JSON", "false").lower()
        if raw_json not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
            raise ValueError("LOG_JSON must be a boolean")
        raw_path = os.environ.get("LOG_FILE", "")
        path = Path(raw_path) if raw_path else None
        if path is not None and not path.is_absolute():
            path = project_root / path
        return cls(
            level=level,
            format=os.environ.get("LOG_FMT", DEFAULT_LOG_FORMAT),
            file_path=path,
            json_format=raw_json in {"true", "1", "yes", "on"},
        )
