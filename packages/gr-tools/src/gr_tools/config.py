"""无业务依赖的公共配置模型；导入时不加载 dotenv 或创建全局单例。"""

from __future__ import annotations

import logging
import os
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import cast

from gr_tools.logging import DEFAULT_LOG_FORMAT as DEFAULT_LOG_FORMAT, configure_logging


_BOOLEAN_VALUES = {
    "true": True,
    "1": True,
    "yes": True,
    "on": True,
    "false": False,
    "0": False,
    "no": False,
    "off": False,
}


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
        if level not in logging.getLevelNamesMapping():
            raise SettingsError("LOG_LEVEL must be a standard logging level")
        json_format = parse_bool(source.get("LOG_JSON"), name="LOG_JSON")
        raw_path = source.get("LOG_FILE", "")
        path = Path(raw_path).expanduser() if raw_path else None
        if path is not None and not path.is_absolute():
            path = project_root / path
        return cls(
            level=level,
            format=source.get("LOG_FMT", DEFAULT_LOG_FORMAT),
            file_path=path,
            json_format=json_format,
        )


class SettingsError(ValueError):
    """配置无效；错误消息不得包含配置原值。"""


def parse_bool(value: str | None, *, name: str) -> bool:
    """按大小写不敏感的合法值解析；空值为 False，未知值抛 SettingsError。

    name 为配置键名，用于生成不包含配置原值的错误消息。
    """
    if not value:
        return False
    parsed = _BOOLEAN_VALUES.get(value.lower())
    if parsed is None:
        raise SettingsError(f"{name} must be a boolean")
    return parsed


def warn_config(message: str, strict: bool) -> None:
    """严格模式拒绝错误配置，开发模式记录安全提示。"""
    if strict:
        raise SettingsError(message) from None
    logging.getLogger(__name__).warning("[Config] %s", message)


def find_project_root(
    start_path: Path | None = None, *, environ: Mapping[str, str] | None = None
) -> Path:
    """按显式根、workspace、Git 根依次定位；跳过不可读或无效的项目文件。"""
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
        try:
            with project.open("rb") as stream:
                metadata: dict[str, object] = tomllib.load(stream)
        except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
            continue
        tool = metadata.get("tool")
        if not isinstance(tool, dict):
            continue
        # TOML 表的键均为字符串；显式保留 isinstance 缩窄后丢失的泛型类型。
        uv = cast(dict[str, object], tool).get("uv")
        if isinstance(uv, dict) and isinstance(cast(dict[str, object], uv).get("workspace"), dict):
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
        return (
            parse_bool(self.values.get("STRICT_MODE"), name="STRICT_MODE")
            or self.values.get("APP_ENV", "").lower() == "prod"
        )


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
    project_root = (root or find_project_root(environ=source)).expanduser().resolve()
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
            _ = os.environ.setdefault(key, value)
    return Environment(project_root, values, target)


def setup_logging(
    config: LoggingConfig,
    *,
    level: str | int | None = None,
    file_path: Path | None = None,
    filters: Sequence[logging.Filter] = (),
) -> None:
    """由程序入口将日志模型适配到公共输出设施。"""
    configure_logging(
        config.level if level is None else level,
        file_path=config.file_path if file_path is None else file_path,
        text_format=config.format,
        json_format=config.json_format,
        filters=filters,
    )
