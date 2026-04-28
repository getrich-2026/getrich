import yaml
from pathlib import Path
from typing import Any, Dict, Optional
from pydantic import PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    host: str = "localhost"
    port: int = 5432
    user: str = "quant"
    password: str = "zedbi4-revSat-nepqik"
    name: str = "getrich"
    url: Optional[str] = None

    @field_validator("url", mode="before")
    @classmethod
    def assemble_db_url(cls, v: Optional[str], info: Any) -> Any:
        if isinstance(v, str) and v:
            return v
        data = info.data
        return f"postgresql://{data['user']}:{data['password']}@{data['host']}:{data['port']}/{data['name']}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore"
    )

    db: DatabaseSettings = DatabaseSettings()

    # 运行时开关 (对应 config.yaml)
    fetcher_enabled: Dict[str, bool] = {}

    @classmethod
    def load_from_yaml(cls, yaml_path: str | Path = "config.yaml") -> "Settings":
        path = Path(yaml_path)
        yaml_data = {}
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f) or {}

        # 将 yaml 数据传递给构造函数
        return cls(**yaml_data)


# 全局单例
settings = Settings.load_from_yaml()
