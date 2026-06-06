"""Signal data model for live signal production."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class Signal:
    """A single trading signal produced by a strategy.

    Maps to the ``signals`` table schema in PostgreSQL.  All optional
    fields default to ``None`` so production code only sets what it has.
    """

    symbol: str
    action: str  # "buy" | "sell" | "hold" | "close"
    signal_type: str = "entry"
    direction: str | None = None  # "long" | "short"
    symbol_name: str | None = None
    exchange: str | None = None
    trigger_price: Decimal | None = None
    target_price: Decimal | None = None
    stop_loss_price: Decimal | None = None
    suggested_quantity: int | None = None
    position_pct: Decimal | None = None
    confidence: Decimal | None = None
    urgency: str = "normal"  # "low" | "normal" | "high" | "critical"
    reason: str | None = None
    trigger_time: datetime | None = None
    status: str = "active"  # "active" | "expired" | "cancelled"
