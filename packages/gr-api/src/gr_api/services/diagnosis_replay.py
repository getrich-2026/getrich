from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from gr_api.diagnosis_calc.replay import ReplayDay, ReplayResult, buy_and_hold
from gr_data.common.replay_evidence import DIVIDEND_SIGNATURE_SQL
from gr_data.db import DictConnection
from psycopg.types.json import Jsonb


async def replay_snapshot(
    conn: DictConnection,
    weights: dict[str, Decimal],
    start: date,
    end: date,
    *,
    expected_hashes: Mapping[str, str] | None = None,
    dividend_signatures: Mapping[str, list] | None = None,
    delisting_hash: str | None = None,
    delist_dates: Mapping[str, str | None] | None = None,
) -> ReplayResult:
    """在调用者固定的只读快照内复核指定股票的买入持有路径。日期为交易日闭区间。"""
    observations: dict[tuple[int, date], ReplayDay] = {}
    id_weights: dict[int, Decimal] = {}
    if (
        not weights
        or any(not w.is_finite() or w <= 0 for w in weights.values())
        or sum(weights.values()) != 1
    ):
        raise ValueError("Expected normalized positive finite portfolio weights")
    if start > end:
        raise ValueError("Invalid replay window")
    if any(
        x is None for x in (expected_hashes, delisting_hash, delist_dates, dividend_signatures)
    ) and any(
        x is not None for x in (expected_hashes, delisting_hash, delist_dates, dividend_signatures)
    ):
        raise ValueError("Replay manifest must bind both corporate action sources")
    async with conn.cursor() as cur:
        if delisting_hash is not None:
            await cur.execute(
                "SELECT 1 FROM market.stock_delisting WHERE raw_sha256=%s LIMIT 1",
                (delisting_hash,),
            )
            if await cur.fetchone() is None:
                raise ValueError("Missing admitted delisting observation")
        await cur.execute(
            """SELECT i.instrument_id, i.symbol, i.exchange, i.list_date,
                      i.delist_date AS metadata_delist_date, d.delist_date,
                      c.through_date, c.raw_sha256
               FROM meta.instruments i
               JOIN LATERAL (
                 SELECT cov.through_date,cov.raw_sha256 FROM finance.dividend_coverage cov
                 WHERE cov.instrument_id=i.instrument_id AND cov.source='tushare'
                   AND (%(hashes)s::jsonb IS NULL OR
                        cov.raw_sha256=(%(hashes)s::jsonb ->> i.instrument_id::text))
                 ORDER BY cov.observed_at DESC,cov.raw_sha256 LIMIT 1
               ) c ON true
               LEFT JOIN LATERAL (
                 SELECT DISTINCT ds.delist_date FROM market.stock_delisting ds
                 WHERE ds.instrument_id=i.instrument_id AND ds.source='tushare'
                   AND (%(delisting)s::text IS NULL OR ds.raw_sha256=%(delisting)s)
               ) d ON true
               WHERE i.asset='stock' AND i.exchange IN ('XSHG','XSHE')
                 AND i.symbol=ANY(%(symbols)s)""",
            {
                "symbols": list(weights),
                "hashes": Jsonb(dict(expected_hashes)) if expected_hashes is not None else None,
                "delisting": delisting_hash,
            },
        )
        stocks = await cur.fetchall()
        if {r["symbol"] for r in stocks} != set(weights) or len(stocks) != len(weights):
            raise ValueError("Missing or ambiguous instrument or dividend coverage")
        calendar = None
        for stock in stocks:
            iid = stock["instrument_id"]
            id_weights[iid] = weights[stock["symbol"]]
            if dividend_signatures is not None:
                await cur.execute(DIVIDEND_SIGNATURE_SQL, (iid, stock["raw_sha256"]))
                row = await cur.fetchone()
                if row is None or dividend_signatures.get(str(iid)) != [
                    row["row_count"],
                    row["digest"],
                ]:
                    raise ValueError("Dividend events differ from admitted snapshot")
            meta_delist, action_delist = stock["metadata_delist_date"], stock["delist_date"]
            if (
                meta_delist is not None
                and action_delist is not None
                and meta_delist != action_delist
            ):
                raise ValueError("Conflicting delisting dates")
            if delist_dates is not None:
                if str(iid) not in delist_dates:
                    raise ValueError("Missing full-universe delisting evidence for instrument")
                admitted = delist_dates[str(iid)]
                delist = date.fromisoformat(admitted) if admitted is not None else None
                if delist != action_delist or (
                    meta_delist is not None and meta_delist <= end and meta_delist != delist
                ):
                    raise ValueError("Delisting evidence differs from admitted snapshot")
            else:
                delist = action_delist or meta_delist
            if (
                stock["list_date"] is None
                or start < stock["list_date"]
                or end > stock["through_date"]
            ):
                raise ValueError("Requested window exceeds verified listing or dividend history")
            await cur.execute(
                """SELECT trading_day,prev_trading_day FROM meta.trading_calendar
                   WHERE exchange=%s AND is_open AND trading_day BETWEEN %s AND %s
                   ORDER BY trading_day""",
                (stock["exchange"], start, end),
            )
            rows = await cur.fetchall()
            days = [r["trading_day"] for r in rows]
            if (
                not days
                or days[0] != start
                or days[-1] != end
                or any(
                    r["prev_trading_day"] != prev for prev, r in zip(days, rows[1:], strict=False)
                )
                or (calendar is not None and days != calendar)
            ):
                raise ValueError("Requested window requires matching complete trading calendars")
            previous = {r["trading_day"]: r["prev_trading_day"] for r in rows}
            calendar = days
            await cur.execute(
                """SELECT * FROM finance.dividend
                   WHERE instrument_id=%s AND raw_sha256=%s AND source='tushare'
                   AND ((ex_date IS NULL AND implementation_date<=%s)
                        OR ex_date BETWEEN %s AND %s)""",
                (iid, stock["raw_sha256"], end, start, end),
            )
            dividends: dict[date, list[tuple[date, Decimal]]] = defaultdict(list)
            multipliers: dict[date, Decimal] = defaultdict(lambda: Decimal(1))
            invalid_events: set[date] = set()
            for event in await cur.fetchall():
                ex, pay = event["ex_date"], event["pay_date"]
                cash, shares = event["cash_per_share"], event["shares_per_share"]
                if ex not in previous:
                    raise ValueError("Unverified corporate action ex-date")
                if (
                    event["implementation_date"] >= ex
                    or event["record_date"] != previous[ex]
                    or cash is None
                    or shares is None
                    or (cash and (pay is None or pay < ex))
                    or (shares and event["share_listing_date"] != ex)
                ):
                    invalid_events.add(ex)
                    continue
                if cash:
                    dividends[ex].append((pay, cash))
                multipliers[ex] += shares
            await cur.execute(
                """SELECT c.trading_day,b.instrument_id AS bar_id,b.open,b.close,
                          b.limit_up,b.price_limit_status,
                          (SELECT count(*) FROM market.stock_suspend_event e
                            WHERE e.instrument_id=%s
                            AND e.trading_day=c.trading_day AND e.source=c.source) AS event_count,
                          EXISTS (SELECT 1 FROM market.stock_suspend_event e
                            WHERE e.instrument_id=%s
                            AND e.trading_day=c.trading_day AND e.source=c.source
                            AND e.suspend_type='S'
                            AND e.suspend_timing IS NULL) AS full_suspend
                   FROM market.stock_suspend_coverage c LEFT JOIN market.stock_bar_1d b
                   ON b.instrument_id=%s AND b.dt=c.trading_day AND b.source=c.source
                   WHERE c.source='tushare' AND c.trading_day BETWEEN %s AND %s""",
                (iid, iid, iid, start, end),
            )
            for row in await cur.fetchall():
                day = row["trading_day"]
                if day in invalid_events:
                    continue
                full = row["event_count"] == 1 and row["full_suspend"] and row["bar_id"] is None
                # 全天停牌标记与真实 bar 冲突时，两者均不能作为估值依据。
                if row["full_suspend"] and not full:
                    continue
                open_price, limit = row["open"], row["limit_up"]
                suspended_at_open = True if full else None if row["event_count"] else False
                limit_at_open = None
                if row["price_limit_status"] == "NO_LIMIT":
                    limit_at_open = False
                elif (
                    suspended_at_open is False
                    and row["price_limit_status"] == "LIMITED"
                    and limit is not None
                    and limit.is_finite()
                    and limit > 0
                    and open_price is not None
                    and open_price.is_finite()
                    and open_price > 0
                ):
                    limit_at_open = open_price >= limit
                observations[iid, day] = ReplayDay(
                    open_price,
                    row["close"],
                    suspended_at_open,
                    limit_at_open,
                    full,
                    multipliers[day],
                    tuple(dividends[day]),
                )
            if delist is not None:
                for day in days:
                    if day >= delist:
                        observations[iid, day] = ReplayDay(None, None, False, False, delisted=True)
    if calendar is None:
        raise ValueError("Empty portfolio")
    return buy_and_hold(id_weights, calendar, observations)
