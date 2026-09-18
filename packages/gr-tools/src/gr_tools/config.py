"""无业务依赖的公共配置模型；导入时不加载 dotenv 或创建全局单例。"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType


DEFAULT_LOG_FORMAT = "[%(asctime)s][%(name)s][%(levelname)s][%(request_id)s] %(message)s"


@dataclass(frozen=True)
class LoggingConfig:
    """进程日志选项。环境加载由应用入口选择时机。"""

    level: str = "INFO"
    format: str = DEFAULT_LOG_FORMAT
    file_path: Path | None = None
    json_format: bool = False

    @classmethod
    def from_env(
        cls, project_root: Path, environ: Mapping[str, str] | None = None
    ) -> LoggingConfig:
        """读取 LOG_*；相对输出路径以调用方提供的根目录解析。"""
        source = os.environ if environ is None else environ
        level = source.get("LOG_LEVEL", "INFO").upper()
        if not isinstance(logging.getLevelName(level), int):
            raise ValueError("LOG_LEVEL must be a standard logging level")
        raw_json = source.get("LOG_JSON", "false").lower()
        if raw_json not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
            raise ValueError("LOG_JSON must be a boolean")
        raw_path = source.get("LOG_FILE", "")
        path = Path(raw_path) if raw_path else None
        if path is not None and not path.is_absolute():
            path = project_root / path
        return cls(
            level=level,
            format=source.get("LOG_FMT", DEFAULT_LOG_FORMAT),
            file_path=path,
            json_format=raw_json in {"true", "1", "yes", "on"},
        )


class SettingsError(ValueError):
    """配置无效；错误消息不得包含配置原值。"""


def parse_bool(value: str | None) -> bool:
    """沿用环境布尔值的既有解释。"""
    return bool(value and value.lower() in {"true", "1", "yes", "on"})


def warn_config(message: str, strict: bool) -> None:
    """严格模式拒绝错误配置，开发模式记录安全提示。"""
    if strict:
        raise SettingsError(message) from None
    logging.getLogger(__name__).warning("[Config] %s", message)


def find_project_root(
    start_path: Path | None = None, *, environ: Mapping[str, str] | None = None
) -> Path:
    """按显式根、workspace、Git 根依次定位；支持从成员目录启动。"""
    source = os.environ if environ is None else environ
    override = source.get("GETRICH_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    start = (start_path or Path.cwd()).resolve()
    if start.is_file():
        start = start.parent
    candidates = [start, *start.parents]
    for candidate in candidates:
        project = candidate / "pyproject.toml"
        if project.is_file() and "[tool.uv.workspace]" in project.read_text(encoding="utf-8"):
            return candidate
    for candidate in candidates:
        if (candidate / ".git").exists():
            return candidate
    return start


@dataclass(frozen=True)
class Environment:
    """单次启动读取的环境快照；不在 repr 中暴露配置值。"""

    root: Path
    values: Mapping[str, str] = field(repr=False)
    env_file: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))

    @property
    def strict(self) -> bool:
        return parse_bool(self.values.get("STRICT_MODE")) or self.values.get("APP_ENV") == "prod"


def load_environment(
    env_file: str | Path | None = None,
    *,
    root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    install: bool = False,
) -> Environment:
    """显式读取环境，进程变量优先；缺少自动候选文件时使用现有环境。

    显式指定但不存在的文件会失败。不会自动创建文件。install 只供 CLI
    兼容直接读取 os.environ 的供应商 SDK；应用实例默认使用独立快照。
    """
    from dotenv import dotenv_values

    source = dict(os.environ if environ is None else environ)
    project_root = (
        (
            root
            or (
                Path(source["GETRICH_ROOT"])
                if source.get("GETRICH_ROOT")
                else find_project_root(environ=source)
            )
        )
        .expanduser()
        .resolve()
    )
    target = Path(env_file).expanduser() if env_file is not None else None
    if target is not None and not target.is_file():
        raise SettingsError("Explicit environment file does not exist")
    if target is None:
        target = next(
            (
                p
                for p in (project_root / ".env", Path.home() / ".config/getrich/.env")
                if p.is_file()
            ),
            None,
        )
    # dotenv 的变量插值依赖进程环境，使用其解析器并以同一来源快照显式解析。
    values: dict[str, str] = {}
    if target is not None:
        from dotenv.variables import parse_variables

        for key, value in dotenv_values(target, interpolate=False).items():
            if value is not None:
                interpolation = {**values, **source}
                values[key] = "".join(
                    atom.resolve(interpolation) for atom in parse_variables(value)
                )
    values.update(source)
    if install:
        for key, value in values.items():
            os.environ.setdefault(key, value)
    return Environment(project_root, values, target)


def setup_logging(
    config: LoggingConfig,
    *,
    level: str | int | None = None,
    file_path: Path | None = None,
    filters: Sequence[logging.Filter] = (),
) -> None:
    """由程序入口将日志模型适配到公共输出设施。"""
    from gr_tools.logging import configure_logging

    configure_logging(
        config.level if level is None else level,
        file_path=config.file_path if file_path is None else file_path,
        text_format=config.format,
        json_format=config.json_format,
        filters=filters,
    )
