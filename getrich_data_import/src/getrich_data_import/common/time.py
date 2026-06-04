from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

import pandas as pd


def to_date_series(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce").dt.date


def to_shanghai_timestamp_series(values: pd.Series) -> pd.Series:
    ts = pd.to_datetime(values, errors="coerce")
    if ts.dt.tz is None:
        return ts.dt.tz_localize(ZoneInfo("Asia/Shanghai"))
    return ts.dt.tz_convert(ZoneInfo("Asia/Shanghai"))


def int_yyyymmdd_to_date(value: int | str) -> date:
    return pd.to_datetime(str(value), format="%Y%m%d").date()

