"""配置加载。

从 YAML 读取配置，并对 ``${ENV}`` 占位与 ``*_env`` 字段做环境变量解析。
- ``${VAR}`` 形式的字符串值 → 替换为环境变量 VAR 的值。
- ``xxx_env: VARNAME`` 字段 → 额外提供 ``xxx`` 解析后的明文（仅在内存中）。

凭证只以「环境变量名」存于配置文件，明文不落盘（见 CLAUDE.md 铁律）。
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from gr_tools.config import Environment, load_environment

from gr_data.common.paths import DEFAULT_RAW_ROOT


_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(value: Any, environ: Mapping[str, str] | None = None) -> Any:
    """递归把 ``${VAR}`` 占位替换为环境变量值（缺失则保留原串并由调用方校验）。"""
    source = os.environ if environ is None else environ
    if isinstance(value, str):

        def repl(m: re.Match[str]) -> str:
            return source.get(m.group(1), m.group(0))

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _expand_env(v, source) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v, source) for v in value]
    return value


def resolve_secret_fields(
    cfg: dict[str, Any], environ: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """对任意 ``*_env`` 字段，注入同级去掉 ``_env`` 后缀的明文键。

    例：``password_env: PGPASSWORD`` → 额外得到 ``password: <env值>``（若环境变量存在）。
    原 ``*_env`` 字段保留，便于排查。
    """
    source = os.environ if environ is None else environ
    if not isinstance(cfg, dict):
        return cfg
    out: dict[str, Any] = {}
    for k, v in cfg.items():
        if isinstance(v, dict):
            out[k] = resolve_secret_fields(v, source)
        else:
            out[k] = v
        if k.endswith("_env") and isinstance(v, str) and v:
            secret = source.get(v)
            if secret is not None:
                out[k[:-4]] = secret
    return out


@dataclass
class Config:
    """已解析配置的薄包装，提供按路径取值的便捷方法。"""

    data: dict[str, Any] = field(default_factory=dict, repr=False)
    environment: Environment | None = field(default=None, repr=False)

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
        """raw 层 parquet 落地根目录。

        优先级：``RAW_PARQUET_ROOT`` 环境变量 > ``config.yaml`` 的
        ``paths.raw_root`` > :data:`DEFAULT_RAW_ROOT`。

        环境变量必须排第一：`AGENTS.md` §3.4 和 `.env.example` 都把
        ``$RAW_PARQUET_ROOT`` 写成落地根目录的真源，但这里过去只读
        ``config.yaml``，而随包发布的 ``config.example.yaml`` 里 ``raw_root``
        恒等于 ``/opt/raw_parquet`` —— 于是环境变量**永远不生效**，配了也没用，
        新机器上一律撞 `/opt` 的权限错。方向同 D-002：环境变量优先。
        """
        source = self.environment.values if self.environment is not None else os.environ
        env_root = source.get("RAW_PARQUET_ROOT", "").strip()
        if env_root:
            return Path(env_root)
        return Path(self.get("paths", "raw_root", default=str(DEFAULT_RAW_ROOT)))


def load_config(
    path: str | Path | None = None, *, environment: Environment | None = None
) -> Config:
    """加载配置文件。path 为空时按 ``config.yaml`` → ``config.example.yaml`` 顺序查找。"""
    env = environment if environment is not None else load_environment()
    _project_root = env.root
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    else:
        cwd = Path.cwd()
        candidates += [cwd / "config.yaml", cwd / "config.example.yaml"]
        # workspace 根，以及 gr-data 包自己的目录（config.example.yaml 随包走）
        candidates += [_project_root / "config.yaml", _project_root / "config.example.yaml"]
        pkg_root = Path(__file__).resolve().parents[3]
        candidates += [pkg_root / "config.yaml", pkg_root / "config.example.yaml"]

    for cand in candidates:
        if cand.is_file():
            raw = yaml.safe_load(cand.read_text(encoding="utf-8")) or {}
            expanded = _expand_env(raw, env.values)
            resolved = resolve_secret_fields(expanded, env.values)
            return Config(resolved, env)

    # 没有配置文件时返回空配置，调用方各自给默认值。
    return Config({}, env)
