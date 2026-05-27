from __future__ import annotations

import pandas as pd

from ..importer import BaseImporter, ImportContext, ResolvedMode
from ..utils import int_yyyymmdd_to_date


class CalendarImporter(BaseImporter):
    name = "calendar"
    target_table = "re.calendar"
    primary_keys = ("exchange", "dt")
    watermark_column = "dt"
    full_replace = True

    def stream_frames(self, ctx: ImportContext, mode: ResolvedMode, since: object | None):
        for path in ctx.store.calendar_paths():
            exchange = path.stem.replace("calendar_", "", 1)
            raw = pd.read_parquet(path)
            dates = raw.index.to_series().map(int_yyyymmdd_to_date).sort_values()
            if mode == "incremental" and since is not None:
                dates = dates[dates > since]
            if dates.empty:
                continue
            df = pd.DataFrame(
                {
                    "exchange": exchange,
                    "dt": dates.values,
                    "is_trading": True,
                    "prev_trading_day": dates.shift(1).values,
                    "next_trading_day": dates.shift(-1).values,
                }
            )
            yield df.where(pd.notna(df), None)

