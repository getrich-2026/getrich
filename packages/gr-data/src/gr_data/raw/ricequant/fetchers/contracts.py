"""米筐 raw fetcher：期货合约参数。

- all_instruments(type='Future') → instruments/future.parquet（SDK 字段原样）
- get_tick_size(普通合约)        → instruments/future_tick.parquet（order_book_id, tick_size）

两者都是**最新快照**。主力／指数连续合约（``IF88``、``IF99``）没有对应的交易所合约，
不查最小变动价位。
"""

from __future__ import annotations

import re

import pandas as pd

from gr_data.common.parquet import write_parquet
from gr_data.common.retry import chunk_list, retry_call, sleep_s
from gr_data.raw.base import BaseFetcher
from gr_data.raw.ricequant.client import RQ_TYPE_MAP


#: 米筐普通期货合约代码：品种字母 + 4 位年月（郑商所也已补齐为 4 位，见米筐合约文档）。
REGULAR_FUTURE = re.compile(r"^([A-Z]+)(\d{4})$")
#: 单次 get_tick_size 的代码数；SDK 未声明上限，取保守值。
TICK_CHUNK = 500


class FutureContractsFetcher(BaseFetcher):
    PROVIDER = "ricequant"
    DATASET = "future_contracts"

    def fetch(self, mode: str = "update") -> int:
        frame = retry_call(
            self.client.all_instruments,
            RQ_TYPE_MAP["future"],
            self.client.market,
            max_retries=self.ctx.max_retries,
            backoff_base=self.ctx.backoff_base,
            logger=self.log,
        )
        if frame is None or frame.empty or "order_book_id" not in frame.columns:
            raise ValueError("RiceQuant future instruments are missing or lack order_book_id")
        frame = frame.reset_index(drop=True)
        codes = sorted(c for c in frame["order_book_id"].astype(str) if REGULAR_FUTURE.match(c))

        ticks: list[pd.Series] = []
        for chunk in chunk_list(codes, TICK_CHUNK):
            sleep_s(self.ctx.sleep_between_requests)
            ticks.append(
                retry_call(
                    self.client.get_tick_size,
                    chunk,
                    max_retries=self.ctx.max_retries,
                    backoff_base=self.ctx.backoff_base,
                    logger=self.log,
                )
            )
        tick = (
            pd.concat(ticks).rename("tick_size").rename_axis("order_book_id").reset_index()
            if ticks
            else pd.DataFrame(columns=["order_book_id", "tick_size"])
        )
        missing = sorted(set(codes) - set(tick["order_book_id"].astype(str)))
        if missing:
            # 不补值：缺最小变动价位的合约在 ingest 时保持 NULL，这里只留痕。
            self.log.warning(
                "RiceQuant tick size missing count=%d samples=%s", len(missing), missing[:5]
            )

        write_parquet(
            frame, self.paths.dataset_file(self.PROVIDER, "instruments", "future"), append=False
        )
        write_parquet(
            tick,
            self.paths.dataset_file(self.PROVIDER, "instruments", "future_tick"),
            append=False,
        )
        self.log.info(
            "RiceQuant future contracts written rows=%d regular=%d ticks=%d",
            len(frame),
            len(codes),
            len(tick),
        )
        return 2
