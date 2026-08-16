"""银河 K 线增量 fetcher（日线/分钟线），按 code + 月分区落盘。

水位：从每个 code 的本地最新分区文件取最大日期，只拉之后的数据并去重追加。
落盘原样保留 SDK 字段（含 kline_time 索引），不归一化。
"""

from __future__ import annotations

import pandas as pd

from gr_data.common.parquet import (
    last_index_date,
    read_parquet_if_exists,
    write_parquet,
)
from gr_data.common.retry import (
    chunk_date_range,
    chunk_list,
    next_int_date,
    retry_call,
    sleep_s,
    today_int,
)
from gr_data.raw.base import BaseFetcher
from gr_data.raw.yinhe.fetchers.reference import INIT_START_DATE, SECURITY_TYPES


class _KlineFetcher(BaseFetcher):
    PROVIDER = "yinhe"
    PERIOD = "day"  # 'day' | 'min1'
    CODE_CHUNK_SIZE = 200
    DATE_CHUNK_DAYS = 120

    def _all_codes(self) -> list[str]:
        codes: list[str] = []
        for st in SECURITY_TYPES.values():
            path = self.paths.dataset_file("yinhe", "hist_code_list", st)
            df = read_parquet_if_exists(path)
            if df is not None and not df.empty:
                codes += [str(c) for c in df["code"].tolist()]
            else:
                codes += [str(c) for c in self.client.get_code_list(st)]
        # 去重保序
        return list(dict.fromkeys(codes))

    def _local_last_date(self, code: str) -> int | None:
        code_dir = self.paths.code_dir(self.PROVIDER, self.DATASET, code)
        if not code_dir.exists():
            return None
        latest: int | None = None
        for f in sorted(code_dir.glob("*.parquet")):
            d = last_index_date(read_parquet_if_exists(f))
            if d is not None and (latest is None or d > latest):
                latest = d
        return latest

    def _start_for(self, code: str, mode: str) -> int:
        floor = INIT_START_DATE
        if self.ctx.start_date:
            floor = max(floor, int(self.ctx.start_date))
        if mode == "init":
            return floor
        last = self._local_last_date(code)
        return max(floor, next_int_date(last, 1)) if last else floor

    def _save(self, code: str, df: pd.DataFrame) -> None:
        if df is None or df.empty:
            return
        if "kline_time" in df.columns:
            df = df.set_index("kline_time")
        df.index = pd.to_datetime(df.index)
        df = df[~df.index.duplicated(keep="last")].sort_index()
        for ym, grp in df.groupby(df.index.strftime("%Y-%m")):
            out = self.paths.code_month_file(self.PROVIDER, self.DATASET, code, ym)
            write_parquet(grp, out, append=True)

    def fetch(self, mode: str = "update") -> int:
        codes = self._all_codes()
        end = today_int()
        n = 0
        for chunk in chunk_list(codes, self.CODE_CHUNK_SIZE):
            # 同块内按各自起始日的最小值统一拉取，再按 code 分发落盘
            starts = {c: self._start_for(c, mode) for c in chunk}
            todo = [c for c, s in starts.items() if s <= end]
            if not todo:
                continue
            floor = min(starts[c] for c in todo)
            for begin, stop in chunk_date_range(floor, end, self.DATE_CHUNK_DAYS):
                result = retry_call(
                    self.client.query_kline,
                    todo,
                    begin,
                    stop,
                    self.PERIOD,
                    max_retries=self.ctx.max_retries,
                    backoff_base=self.ctx.backoff_base,
                    logger=self.log,
                )
                for code, df in (result or {}).items():
                    self._save(str(code), df)
                    n += 1
                sleep_s(self.ctx.sleep_between_requests)
            self.log.info("kline[%s] 处理 %d codes", self.PERIOD, len(todo))
        return n


class KlineDayFetcher(_KlineFetcher):
    DATASET = "kline_day"
    PERIOD = "day"
    CODE_CHUNK_SIZE = 200
    DATE_CHUNK_DAYS = 120


class KlineMin1Fetcher(_KlineFetcher):
    DATASET = "kline_min1"
    PERIOD = "min1"
    CODE_CHUNK_SIZE = 100
    DATE_CHUNK_DAYS = 5
