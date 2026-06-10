from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterable, Iterator, TypeVar

import pandas as pd


T = TypeVar("T")


def chunks(items: list[T], size: int) -> Iterator[list[T]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def clean_code(value: object) -> str:
    return str(value).strip().upper()


def exchange_from_code(code: str) -> str:
    suffix = code.rsplit(".", 1)[-1].upper() if "." in code else ""
    return {"SH": "SH", "SZ": "SZ"}.get(suffix, suffix)


def to_date_series(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce").dt.date


def int_yyyymmdd_to_date(value: int | str) -> date:
    return pd.to_datetime(str(value), format="%Y%m%d").date()


def iter_existing(paths: Iterable[Path]) -> Iterator[Path]:
    for path in paths:
        if path.exists():
            yield path

