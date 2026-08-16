"""配置加载。

从 YAML 读取配置，并对 ``${ENV}`` 占位与 ``*_env`` 字段做环境变量解析。
- ``${VAR}`` 形式的字符串值 → 替换为环境变量 VAR 的值。
- ``xxx_env: VARNAME`` 字段 → 额外提供 ``xxx`` 解析后的明文（仅在内存中）。

凭证只以「环境变量名」存于配置文件，明文不落盘（见 CLAUDE.md 铁律）。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# 项目根目录的 .env 文件（若存在则自动加载到 os.environ）
_project_root = Path(__file__).resolve().parents[3]
_dotenv_path = _project_root / ".env"
if _dotenv_path.is_file():
    load_dotenv(_dotenv_path)

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(value: Any) -> Any:
    """递归把 ``${VAR}`` 占位替换为环境变量值（缺失则保留原串并由调用方校验）。"""
    if isinstance(value, str):
        def repl(m: re.Match[str]) -> str:
            return os.environ.get(m.group(1), m.group(0))

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def resolve_secret_fields(cfg: dict[str, Any]) -> dict[str, Any]:
    """对任意 ``*_env`` 字段，注入同级去掉 ``_env`` 后缀的明文键。

    例：``password_env: PGPASSWORD`` → 额外得到 ``password: <env值>``（若环境变量存在）。
    原 ``*_env`` 字段保留，便于排查。
    """
    if not isinstance(cfg, dict):
        return cfg
    out: dict[str, Any] = {}
    for k, v in cfg.items():
        if isinstance(v, dict):
            out[k] = resolve_secret_fields(v)
        else:
            out[k] = v
        if k.endswith("_env") and isinstance(v, str) and v:
            secret = os.environ.get(v)
            if secret is not None:
                out[k[:-4]] = secret
    return out


@dataclass
class Config:
    """已解析配置的薄包装，提供按路径取值的便捷方法。"""

    data: dict[str, Any] = field(default_factory=dict)

    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self.data
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def section(self, *keys: str) -> dict[str, Any]:
        node = self.get(*keys, default={})
        return node if isinstance(node, dict) else {}

    @property
    def raw_root(self) -> Path:
        return Path(self.get("paths", "raw_root", default="/opt/raw_parquet"))


def load_config(path: str | Path | None = None) -> Config:
    """加载配置文件。path 为空时按 ``config.yaml`` → ``config.example.yaml`` 顺序查找。"""
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    else:
        cwd = Path.cwd()
        candidates += [cwd / "config.yaml", cwd / "config.example.yaml"]
        here = Path(__file__).resolve().parents[3]
        candidates += [here / "config.yaml", here / "config.example.yaml"]

    for cand in candidates:
        if cand.is_file():
            raw = yaml.safe_load(cand.read_text(encoding="utf-8")) or {}
            expanded = _expand_env(raw)
            resolved = resolve_secret_fields(expanded)
            return Config(resolved)

    # 没有配置文件时返回空配置，调用方各自给默认值。
    return Config({})
