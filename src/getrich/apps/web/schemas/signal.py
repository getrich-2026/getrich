"""信号模块的请求体 Pydantic 模型。

响应统一直接 dict 返回（SQL 行已是 dict_row），不强制 schema 包装。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ExecuteSignalIn(BaseModel):
    """POST /signals/{signal_id}/execute 请求体。"""

    executed_price: float | None = Field(default=None, ge=0)
    executed_quantity: int | None = Field(default=None, ge=0)
    executed_at: datetime | None = None
    note: str | None = Field(default=None, max_length=500)
