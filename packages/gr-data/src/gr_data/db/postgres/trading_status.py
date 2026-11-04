"""从交易日历、行情和已验证停复牌事件读取 D-023 日级状态。"""

from __future__ import annotations

from datetime import date

import pandas as pd
import psycopg

from gr_data.common.trading_status import resolve_trading_status


def load_stock_trading_status(
    conn: psycopg.Connection,
    instrument_ids: list[int],
    start: date,
    end: date,
    *,
    source: str = "tushare",
) -> pd.DataFrame:
    """返回指定标的在日历开市日的状态，包括没有 bar 的全天停牌／未知日。

    只读当前观察，不声称历史 PIT。范围为 Asia/Shanghai 交易日期闭区间，
    不跨日填充；包含上市当日、排除退市日期之后。缺少该交易所日历时拒绝，
    不把其他交易所日历套到北交所。输入 ID 必须全部是已知股票。
    输出列 instrument_id、trading_day、trading_status；峰值内存 O(标的数×交易日数)。

    Raises:
        ValueError: 日期逆序、未知标的或交易日历不完整。
    """
    if start > end:
        raise ValueError("start must not exceed end")
    columns = ["instrument_id", "trading_day", "trading_status"]
    ids = sorted(set(instrument_ids))
    if not ids:
        return pd.DataFrame(columns=columns)
    rows = conn.execute(
        "SELECT instrument_id, exchange FROM meta.instruments "
        "WHERE instrument_id=ANY(%s) AND asset='stock'",
        (ids,),
    ).fetchall()
    if {row[0] for row in rows} != set(ids):
        raise ValueError("Unknown or non-stock instrument IDs")
    for exchange in {row[1] for row in rows}:
        count = conn.execute(
            "SELECT count(*) FROM meta.trading_calendar "
            "WHERE exchange=%s AND trading_day BETWEEN %s AND %s",
            (exchange, start, end),
        ).fetchone()[0]
        if count != (end - start).days + 1:
            raise ValueError(f"Incomplete trading calendar for {exchange}")
    cur = conn.execute(
        """
        WITH events AS (
            SELECT instrument_id, trading_day,
                   bool_or(suspend_type='S' AND suspend_timing IS NULL) AS full_suspend,
                   bool_or(suspend_type='S' AND suspend_timing IS NOT NULL) AS intraday_suspend,
                   bool_or(suspend_type='R') AS resumed
            FROM market.stock_suspend_event
            WHERE instrument_id=ANY(%s) AND trading_day BETWEEN %s AND %s AND source=%s
            GROUP BY instrument_id, trading_day
        )
        SELECT i.instrument_id, c.trading_day, b.instrument_id IS NOT NULL AS has_bar,
               p.trading_day IS NOT NULL AS covered,
               COALESCE(e.full_suspend,false) AS full_suspend,
               COALESCE(e.intraday_suspend,false) AS intraday_suspend,
               COALESCE(e.resumed,false) AS resumed
        FROM meta.instruments i
        JOIN meta.trading_calendar c ON c.exchange=i.exchange AND c.is_open
        LEFT JOIN market.stock_bar_1d b ON b.instrument_id=i.instrument_id
             AND b.dt=c.trading_day AND b.source=%s
        LEFT JOIN events e ON e.instrument_id=i.instrument_id AND e.trading_day=c.trading_day
        LEFT JOIN market.stock_suspend_coverage p ON p.trading_day=c.trading_day AND p.source=%s
        WHERE i.instrument_id=ANY(%s) AND c.trading_day BETWEEN %s AND %s
          AND i.list_date IS NOT NULL AND c.trading_day>=i.list_date
          AND (i.delist_date IS NULL OR c.trading_day<=i.delist_date)
        ORDER BY i.instrument_id, c.trading_day
        """,
        (ids, start, end, source, source, source, ids, start, end),
    )
    result = pd.DataFrame(cur.fetchall(), columns=[column.name for column in cur.description])
    result["trading_status"] = resolve_trading_status(result.drop(columns=columns[:2]))
    return result[columns]
