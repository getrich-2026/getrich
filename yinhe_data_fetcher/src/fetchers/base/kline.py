"""KlineFetcher - K线抽象基类 (仍然是父类, 不可直接实例化).

所有具体 K线 fetcher (日线 / 5分钟 / 1分钟 ...) 共享的逻辑集中在这里.
具体 period 的子类见 ``src/fetchers/impl/kline_*.py``, 只需要声明几个类常量.
"""

from __future__ import annotations

from typing import Any, ClassVar, Iterator

import pandas as pd

from ...utils import (
    chunk_date_range,
    chunk_list,
    last_index_date,
    read_parquet_if_exists,
    to_int_date,
    today_int,
    write_parquet,
)
from .incremental import IncrementalFetcher


# 合法 period 名称 -> AmazingData.Period 枚举成员名
PERIOD_ATTR: dict[str, str] = {
    "day": "day",
    "min1": "min1",
    "min3": "min3",
    "min5": "min5",
    "min10": "min10",
    "min15": "min15",
    "min30": "min30",
    "min60": "min60",
    "min120": "min120",
    "week": "week",
    "month": "month",
    "season": "season",
    "year": "year",
}


class KlineFetcher(IncrementalFetcher):
    """K 线抓取抽象基类.

    具体子类需要声明:
        NAME             - data/ 子目录名 & registry key
        PERIOD           - "day" / "min5" / "min1" / ...
        SECURITY_TYPES   - 抓取的 security_type 列表
        INIT_START_DATE  - init 模式的起点
        CODE_CHUNK_SIZE  - code 切块大小
        DATE_CHUNK_DAYS  - 日期切块大小

    落盘策略: 每个 code 一个 parquet 文件
        data/<NAME>/<code>.parquet
    """

    PERIOD: ClassVar[str] = ""
    SECURITY_TYPES: ClassVar[list[str]] = []

    def _pre_run(self, mode) -> None:
        if not self.PERIOD:
            raise ValueError(f"{type(self).__name__}.PERIOD must be set")
        if self.PERIOD not in PERIOD_ATTR:
            raise ValueError(
                f"unknown PERIOD {self.PERIOD!r}, valid: {list(PERIOD_ATTR)}"
            )
        if not self.SECURITY_TYPES:
            raise ValueError(f"{type(self).__name__}.SECURITY_TYPES must be set")

        self._market = self.client.market_data(self.client.calendar)
        # AmazingData SDK exposes period enum under `AmazingData.constant.Period`
        # (some versions do not provide `AmazingData.Period`).
        period_enum = self.client.ad.constant.Period
        self._period_value = getattr(period_enum, PERIOD_ATTR[self.PERIOD]).value
        self.log.info(
            "[%s] period=%s (value=%s)", self.NAME, self.PERIOD, self._period_value
        )

        # 一次性拉所有 security_type 的 code_list
        all_codes: list[str] = []
        for st in self.SECURITY_TYPES:
            codes = self.client.base_data.get_code_list(security_type=st)
            codes = [str(c) for c in list(codes)]
            self.log.info("[%s] security_type=%s codes=%d", self.NAME, st, len(codes))
            all_codes.extend(codes)
        seen: set[str] = set()
        uniq: list[str] = []
        for c in all_codes:
            if c not in seen:
                seen.add(c)
                uniq.append(c)
        self._all_codes: list[str] = uniq
        self.log.info("[%s] total unique codes=%d", self.NAME, len(uniq))

    def _iter_update_keys(self) -> list[Any]:
        return list(self._all_codes)

    def _last_local_date(self, key: Any) -> int | None:
        p = self.data_dir / f"{key}.parquet"
        df = read_parquet_if_exists(p)
        return last_index_date(df)

    def _fetch_one(self, task: dict[str, Any]) -> Any:
        return self._market.query_kline(
            task["code_chunk"],
            begin_date=task["begin_date"],
            end_date=task["end_date"],
            period=self._period_value,
        )

    def _save_chunk(self, task: dict[str, Any], result: Any) -> None:
        if not isinstance(result, dict):
            self.log.error("unexpected kline return type %s", type(result))
            return
        total = 0
        for code, df in result.items():
            if df is None or not isinstance(df, pd.DataFrame) or df.empty:
                continue
            df = df.copy()
            if df.index.name is None:
                df.index.name = "kline_time"
            df = df[~df.index.duplicated(keep="last")]
            out = self.data_dir / f"{code}.parquet"
            write_parquet(df, out, append=True)
            total += len(df)
        self.log.info(
            "[%s] wrote %d rows across %d codes (task=%s)",
            self.NAME,
            total,
            len(result),
            task.get("label"),
        )

    def _iter_tasks_for_range(
        self,
        keys: list[Any],
        begin_date: int,
        end_date: int,
    ) -> Iterator[dict[str, Any]]:
        begin_date = to_int_date(begin_date)
        end_date = min(to_int_date(end_date), today_int())
        if begin_date > end_date:
            return
        for code_chunk in chunk_list(keys, self.CODE_CHUNK_SIZE):
            for s, e in chunk_date_range(begin_date, end_date, self.DATE_CHUNK_DAYS):
                yield {
                    "code_chunk": list(code_chunk),
                    "begin_date": s,
                    "end_date": e,
                    "label": (
                        f"{self.PERIOD} n={len(code_chunk)} [{s},{e}] "
                        f"e.g. {code_chunk[0]}"
                    ),
                }
