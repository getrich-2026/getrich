"""从本地 V2 隔离库的同一只读快照验证组合历史回放。"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import date
from decimal import Decimal

from gr_api.services import diagnosis_publication as publication
from gr_api.services.diagnosis_replay import replay_snapshot
from gr_data.config import load_postgres, make_pg_dsn
from gr_data.db import DictConnection
from gr_tools.config import load_environment
from psycopg.rows import dict_row


async def _run() -> None:
    """开发验收入口，输出税前、未扣交易成本的标准化组合净值。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument(
        "--holding",
        required=True,
        action="append",
        metavar="SYMBOL=WEIGHT",
        help="股票代码和正权重小数，所有权重之和须为 1。",
    )
    parser.add_argument("--publication", help="固定诊断发布 ID；省略时读取最新原始观察。")
    args = parser.parse_args()
    weights = {}
    for value in args.holding:
        symbol, weight = value.split("=", 1)
        if symbol in weights:
            raise ValueError("Duplicate symbol")
        weights[symbol] = Decimal(weight)
    async with await DictConnection.connect(
        make_pg_dsn(load_postgres(load_environment())), row_factory=dict_row
    ) as conn:
        await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        hashes, delisting, delist_dates = None, None, None
        replay = {}
        if args.publication:
            version = await publication.require_publication(conn, args.publication)
            replay = version["available_options"].get("replay") or {}
            if replay.get("version") != "pa12-local-v1" or args.end > date.fromisoformat(
                replay["through_date"]
            ):
                raise ValueError("Replay window exceeds admitted publication")
            hashes, delisting = replay["dividend_sha256"], replay["delisting_sha256"]
            delist_dates = replay.get("delist_dates")
            await publication.require_coverage(
                conn,
                args.start,
                args.end,
                (
                    "market.stock_bar_1d",
                    "meta.trading_calendar",
                    "market.stock_suspend_event",
                    "market.stock_suspend_coverage",
                ),
            )
        result = await replay_snapshot(
            conn,
            weights,
            args.start,
            args.end,
            expected_hashes=hashes,
            dividend_signatures=replay.get("dividend_signatures") if args.publication else None,
            delisting_hash=delisting,
            delist_dates=delist_dates,
        )
    print(
        json.dumps(
            {
                "publication": args.publication,
                "source_view": "published" if args.publication else "latest_observation",
                "assumptions": "税前、小数股、未扣交易成本、无成交量冲击",
                "stopped_on": result.stopped_on,
                "reason": result.reason,
                "instrument_id": result.instrument_id,
                "unexecuted": [asdict(item) for item in result.unexecuted],
                "series": [
                    {"day": p.day, "nav": p.nav, "cash": p.cash, "receivable": p.receivable}
                    for p in result.points
                ],
            },
            default=str,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(_run())
