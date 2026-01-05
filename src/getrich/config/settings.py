"""Settings module for GetRich quantitative research system."""

import os
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def _find_project_root() -> Path | None:
    """向上查找项目根目录标记文件, 找到则返回路径。"""

    markers = ("pyproject.toml", ".env", ".git")
    current = Path(__file__).resolve().parent

    for _ in range(6):  # 限制向上查找层数, 防止无限循环
        if any((current / marker).exists() for marker in markers):
            return current
        if current.parent == current:
            break
        current = current.parent

    return None


if load_dotenv:
    project_root = _find_project_root()
    env_path = project_root / ".env" if project_root else None

    if env_path and env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()


def get_clickhouse_config() -> dict[str, Any]:
    """
    从.env文件或环境变量读取ClickHouse数据库配置。

    Returns:
        dict[str, Any]: 包含以下键的配置字典:
            - host: ClickHouse服务器地址
            - port: ClickHouse服务器端口
            - user: 用户名
            - password: 密码
            - database: 数据库名

    Note:
        如果环境变量不存在, 使用默认值:
        - DB_HOST: "192.168.1.60"
        - DB_PORT: "8123"
        - DB_USER: "default"
        - DB_PASSWORD: "getrich"
        - DB_NAME: "default"
    """
    return {
        "host": os.getenv("DB_HOST", "192.168.1.60"),
        "port": int(os.getenv("DB_PORT", "8123")),
        "user": os.getenv("DB_USER", "default"),
        "password": os.getenv("DB_PASSWORD", "getrich"),
        "database": os.getenv("DB_NAME", "default"),
    }
