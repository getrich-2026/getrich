from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Protocol

import pandas as pd


@dataclass(frozen=True)
class SourceCoverage:
    calendar_files: int
    instruments: dict[str, int]
    kline_day_files: int
    kline_min1_files: int


class HistoryDataSource(Protocol):
    name: str

    def scan(self) -> SourceCoverage: ...

    def calendar_frames(self) -> Iterable[pd.DataFrame]: ...

    def instrument_frame(self) -> pd.DataFrame: ...

    def future_contract_frame(self) -> pd.DataFrame: ...

    def option_contract_frame(self) -> pd.DataFrame: ...

    def symbol_map_frame(self) -> pd.DataFrame: ...

    def bar_frames(
        self,
        *,
        asset: str,
        freq: str,
        since: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        symbols: list[str] | None = None,
    ) -> Iterable[pd.DataFrame]: ...


def require_dir(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"data directory does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"not a directory: {path}")
    return path
