"""DS06 发布及读取共用的规范事件指纹，含完整经济键与回放字段。"""

from __future__ import annotations


DIVIDEND_SIGNATURE_SQL = """
    SELECT count(*) AS row_count,
           encode(sha256(convert_to(COALESCE(jsonb_agg(jsonb_build_array(
             period_end, implementation_date, record_date, ex_date, pay_date, share_listing_date,
             cash_per_share, shares_per_share
           ) ORDER BY period_end, implementation_date), '[]'::jsonb)::text,'UTF8')),'hex') AS digest
    FROM finance.dividend WHERE instrument_id=%s AND raw_sha256=%s AND source='tushare'
"""
