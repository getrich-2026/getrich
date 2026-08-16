"""Run configuration capture for reproducibility."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any

from gr_backtest.time import require_shanghai_aware
from gr_backtest.types import FREQ_TO_MINUTES, Frequency


def _to_bytes(value: Any) -> bytes:
    """Serialize a value for deterministic hashing."""
    if isinstance(value, Decimal):
        return str(value).encode("utf-8")
    if isinstance(value, datetime):
        return value.isoformat().encode("utf-8")
    if isinstance(value, Mapping):
        items = sorted(value.items(), key=lambda item: str(item[0]))
        return b"{" + b",".join(_to_bytes(k) + b":" + _to_bytes(v) for k, v in items) + b"}"
    if isinstance(value, tuple):
        return b"(" + b",".join(_to_bytes(v) for v in value) + b")"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return b"[" + b",".join(_to_bytes(v) for v in value) + b"]"
    return str(value).encode("utf-8")


@dataclass(frozen=True)
class RunConfig:
    """Immutable snapshot of all parameters that define a backtest run."""

    run_id: str
    strategy_name: str
    symbols: tuple[str, ...]
    start: datetime
    end: datetime
    initial_cash: Decimal
    freq: str = "1d"
    extra_freqs: tuple[str, ...] = ()
    execution_lag_bars: int = 1
    strategy_names: tuple[str, ...] = ()
    strategy_freqs: tuple[tuple[str, str], ...] = ()
    strategy_params: dict[str, object] | None = None
    risk_config: dict[str, object] | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must be non-empty")
        if not self.strategy_name.strip():
            raise ValueError("strategy_name must be non-empty")
        if not self.symbols:
            raise ValueError("symbols must be non-empty")
        require_shanghai_aware(self.start)
        require_shanghai_aware(self.end)
        if self.start >= self.end:
            raise ValueError("start must be earlier than end")
        if not isinstance(self.initial_cash, Decimal):
            raise ValueError("initial_cash must be decimal.Decimal")
        if self.initial_cash < Decimal("0"):
            raise ValueError("initial_cash must be non-negative")
        if self.execution_lag_bars < 1:
            raise ValueError("execution_lag_bars must be at least 1")
        if not Frequency.is_valid(self.freq):
            raise ValueError(
                f"freq must be one of {sorted(Frequency.all_values())}, got {self.freq!r}"
            )

        # Validate extra_freqs
        if self.extra_freqs:
            valid = sorted(Frequency.all_values())
            for ef in self.extra_freqs:
                if not Frequency.is_valid(ef):
                    raise ValueError(
                        f"extra_freqs contains invalid frequency {ef!r}. Valid: {valid}"
                    )

            if len(self.extra_freqs) != len(set(self.extra_freqs)):
                raise ValueError("extra_freqs contains duplicate frequencies")

            if self.freq in self.extra_freqs:
                raise ValueError(f"extra_freqs must not contain the primary freq {self.freq!r}")

            primary_minutes = FREQ_TO_MINUTES[self.freq]
            for ef in self.extra_freqs:
                ef_minutes = FREQ_TO_MINUTES[ef]
                if ef_minutes <= primary_minutes:
                    raise ValueError(
                        f"extra_freq {ef!r} ({ef_minutes}m) must be coarser "
                        f"than primary freq {self.freq!r} ({primary_minutes}m)"
                    )

        # Validate strategy_freqs
        if self.strategy_freqs:
            for _s_name, sf in self.strategy_freqs:
                if not Frequency.is_valid(sf):
                    raise ValueError(
                        f"strategy_freqs contains invalid frequency {sf!r}. "
                        f"Valid: {sorted(Frequency.all_values())}"
                    )

        if self.created_at is not None:
            require_shanghai_aware(self.created_at)

    def fingerprint(self) -> str:
        """Return a deterministic SHA-256 hex digest of the config content.

        Uses all fields except ``run_id`` and ``created_at`` so that logically
        identical configs produce the same fingerprint regardless of when or
        under which identity they ran.
        """
        h = sha256()
        h.update(_to_bytes(self.strategy_name))
        h.update(_to_bytes(self.strategy_names))
        h.update(_to_bytes(self.strategy_freqs))
        h.update(_to_bytes(self.symbols))
        h.update(_to_bytes(self.start))
        h.update(_to_bytes(self.end))
        h.update(_to_bytes(self.initial_cash))
        h.update(_to_bytes(self.freq))
        h.update(_to_bytes(self.extra_freqs))
        h.update(_to_bytes(self.execution_lag_bars))
        h.update(_to_bytes(self.strategy_params))
        h.update(_to_bytes(self.risk_config))
        return h.hexdigest()

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable dict (Decimal→str, datetime→isoformat)."""
        return {
            "symbols": list(self.symbols),
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "initial_cash": str(self.initial_cash),
            "freq": self.freq,
            "strategy_names": list(self.strategy_names),
            "strategy_freqs": list(self.strategy_freqs),
            "strategy_params": self.strategy_params,
            "execution_lag_bars": self.execution_lag_bars,
            "risk_config": self.risk_config,
        }
