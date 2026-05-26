from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(slots=True)
class BarEvent:
    """标准化 1 分钟 K 线事件，字段与 MinBarTable.table_schema 完全对齐。"""

    symbol: str
    type: str
    dt: date
    bar_time: datetime
    pre_close: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    amount: float = 0.0
    open_interest: float = 0.0
    settle: float = 0.0
    pre_settle: float = 0.0
    local_time: datetime = field(default_factory=datetime.now)
    provider: str = "insight"


if __name__ == "__main__":
    from datetime import date, datetime

    e = BarEvent(
        symbol="600000.SH",
        type="stock",
        dt=date.today(),
        bar_time=datetime.now(),
        open=10.5,
        close=10.8,
    )
    print(e)
