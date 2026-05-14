"""交易日历 - FullReplace."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, ClassVar

import pandas as pd

from ...utils import write_parquet
from ..base import FullReplaceFetcher


class CalendarFetcher(FullReplaceFetcher):
    """抓取各市场交易日历.

    落盘: data/calendar/calendar_<market>.parquet
    """

    NAME = "calendar"

    MARKETS: ClassVar[list[str]] = ["SH"]

    def _iter_tasks(self, mode) -> Iterator[dict[str, Any]]:
        for m in self.MARKETS:
            yield {"market": m, "label": f"calendar market={m}"}

    def _fetch_one(self, task: dict[str, Any]) -> Any:
        return self.client.base_data.get_calendar(market=task["market"])

    def _save_chunk(self, task: dict[str, Any], result: Any) -> None:
        market = task["market"]
        cal = [int(x) for x in list(result)]
        df = pd.DataFrame({"date": cal})
        df.set_index("date", inplace=True)
        out = self.data_dir / f"calendar_{market}.parquet"
        write_parquet(df, out, append=False)
        self.log.info("write %s (%d rows)", out, len(df))
