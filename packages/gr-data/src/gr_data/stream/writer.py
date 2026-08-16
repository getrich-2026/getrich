"""实时 tick 写入 PostgreSQL（realtime.tick_buffer）。"""

from __future__ import annotations

from collections.abc import Sequence

import psycopg

from gr_data.logging import get_logger
from gr_data.stream.base import TickEvent


log = get_logger("stream.writer")

_COLUMNS = (
    "instrument_id",
    "dt",
    "trading_day",
    "last",
    "volume",
    "amount",
    "bid1",
    "ask1",
    "bid_vol1",
    "ask_vol1",
    "open_interest",
    "source",
)


class PgTickWriter:
    """批量 upsert TickEvent 进 realtime.tick_buffer。"""

    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def write(self, events: Sequence[TickEvent]) -> int:
        if not events:
            return 0
        rows = [
            (
                e.instrument_id,
                e.dt,
                e.trading_day,
                e.last,
                e.volume,
                e.amount,
                e.bid1,
                e.ask1,
                e.bid_vol1,
                e.ask_vol1,
                e.open_interest,
                e.source,
            )
            for e in events
        ]
        col_idents = ", ".join(f'"{c}"' for c in _COLUMNS)
        with self.conn.cursor() as cur:
            cur.execute(
                "CREATE TEMP TABLE _stage_tick (LIKE realtime.tick_buffer INCLUDING DEFAULTS) "
                "ON COMMIT DROP"
            )
            with cur.copy(f"COPY _stage_tick ({col_idents}) FROM STDIN") as cp:
                for row in rows:
                    cp.write_row(row)
            update = ", ".join(
                f'"{c}" = EXCLUDED."{c}"' for c in _COLUMNS if c not in ("instrument_id", "dt")
            )
            cur.execute(
                f"INSERT INTO realtime.tick_buffer ({col_idents}) "
                f"SELECT {col_idents} FROM _stage_tick "
                f"ON CONFLICT (instrument_id, dt) DO UPDATE SET {update}"
            )
            n = cur.rowcount
        self.conn.commit()
        return n
