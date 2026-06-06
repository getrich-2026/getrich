"""后台导入模块请求体模型。"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


ImportType = Literal["strategy_daily_returns", "strategy_signals"]
ImportMode = Literal["upsert", "insert_only"]
ReturnCalcMethod = Literal["compound", "simple"]


class StrategyUpsertIn(BaseModel):
    """策略基础信息创建或更新请求体。"""

    strategy_code: str = Field(min_length=3, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    strategy_type: str = Field(default="manual", min_length=1, max_length=32)
    summary: str | None = Field(default=None, max_length=500)
    description: str | None = None
    detail_html: str | None = None
    category_id: str | None = Field(default=None, max_length=64)
    asset_class: str = Field(min_length=1, max_length=32)
    market: str = Field(default="cn", min_length=1, max_length=32)
    risk_level: Literal["low", "medium", "high"]
    run_status: str = Field(default="paper", max_length=32)
    pub_status: str = Field(default="draft", max_length=32)
    author_id: str
    cover_image: str | None = Field(default=None, max_length=512)
    subscription_monthly: str = Field(default="0")
    subscription_yearly: str = Field(default="0")
    backtest_start: date | None = None
    backtest_end: date | None = None


class ImportPreviewIn(BaseModel):
    """CSV 导入预检请求体。"""

    import_type: ImportType
    csv_text: str = Field(min_length=1)
    file_name: str = Field(min_length=1, max_length=256)
    strategy_code: str | None = Field(default=None, max_length=64)
    mode: ImportMode = "upsert"
    return_calc_method: ReturnCalcMethod = "compound"
    initial_nav: float = Field(default=1.0, gt=0)
    trading_days_per_year: int = Field(default=252, ge=1, le=366)
    risk_free_rate: float = 0.0
