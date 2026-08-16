"""stream 全链路测试（需要 docker PG）：Fake SDK 回调 → bridge → PgTickWriter → PG。"""

from __future__ import annotations

from datetime import datetime

import pytest
from gr_data.common.ownership import OwnershipManager
from gr_data.stream import PgTickWriter
from gr_data.stream.insight import InsightStreamHandler


pytestmark = pytest.mark.integration


class _FakeTick:
    def __init__(self, code, last, vol):
        self.htsc_code = code
        self.time = datetime(2024, 1, 2, 9, 30)
        self.last = last
        self.volume = vol
        self.value = last * vol


class _FakeRealtimeSdk:
    """模拟 SDK：subscribe 时立即对每个 symbol 触发一次回调。"""

    def subscribe(self, symbols, callback):
        for s in symbols:
            callback(_FakeTick(s, 10.5, 1000))


def _seed_instrument(conn, symbol, asset="stock", exch="XSHG"):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO meta.instruments (symbol, asset, exchange, status) "
            "VALUES (%s, %s, %s, 'active') RETURNING instrument_id",
            (symbol, asset, exch),
        )
        return cur.fetchone()[0]


def test_stream_flow(pg_conn):
    iid = _seed_instrument(pg_conn, "600000.SH")
    pg_conn.commit()

    handler = InsightStreamHandler(pg_conn, sdk=_FakeRealtimeSdk(), symbol_to_id={"600000.SH": iid})
    handler.claim_ownership()
    handler.subscribe(["600000.SH"])

    events = handler.bridge.drain(timeout=1.0)
    assert len(events) == 1
    assert events[0].instrument_id == iid

    writer = PgTickWriter(pg_conn)
    n = writer.write(events)
    assert n == 1

    with pg_conn.cursor() as cur:
        cur.execute("SELECT instrument_id, last, source FROM realtime.tick_buffer")
        row = cur.fetchone()
    assert row[0] == iid and float(row[1]) == 10.5 and row[2] == "insight"

    owner = OwnershipManager(pg_conn).owner("realtime.tick_buffer")
    assert owner.provider == "insight" and owner.channel == "stream"
