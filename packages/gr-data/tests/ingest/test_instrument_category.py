"""classify.instrument_category 的 ETF 规则：按 meta.etf_profile 映射，无法确定的不写。"""

from __future__ import annotations

import json
from datetime import date

from gr_data.ingest.base import IngestContext
from gr_data.ingest.tushare.importers.classify import InstrumentCategoryImporter


def _instrument(cur, symbol: str, asset: str, exchange: str) -> int:
    cur.execute(
        "INSERT INTO meta.instruments(symbol, asset, exchange, list_date) "
        "VALUES (%s, %s, %s, %s) RETURNING instrument_id",
        (symbol, asset, exchange, date(2020, 1, 2)),
    )
    return cur.fetchone()[0]


def test_etf_category_follows_fund_type_and_channel(pg_conn, tmp_raw_root):
    """股票型／债券型／货币型且纯境内才写；其他类型、QDII、无档案的跳过并记质量检查。"""
    with pg_conn.cursor() as cur:
        stock = _instrument(cur, "600000.SH", "stock", "XSHG")
        cases = {
            "510300.SH": ("股票型", "纯境内"),
            "511010.SH": ("债券型", "纯境内"),
            "511880.SH": ("货币型", "纯境内"),
            "518880.SH": ("其他", "纯境内"),
            "513100.SH": ("股票型", "QDII"),
            "159999.SZ": (None, None),  # 无档案：fund_basic 未匹配或档案未导入
        }
        ids = {}
        for symbol, (fund_type, channel) in cases.items():
            ids[symbol] = _instrument(cur, symbol, "etf", "XSHG" if symbol[-2:] == "SH" else "XSHE")
            if fund_type is not None:
                cur.execute(
                    "INSERT INTO meta.etf_profile(instrument_id, fund_type, channel, source) "
                    "VALUES (%s, %s, %s, 'tushare')",
                    (ids[symbol], fund_type, channel),
                )
    pg_conn.commit()

    InstrumentCategoryImporter(pg_conn, IngestContext(paths=tmp_raw_root)).run()

    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT instrument_id, asset_category, market FROM classify.instrument_category "
            "ORDER BY instrument_id"
        )
        written = cur.fetchall()
        cur.execute(
            "SELECT detail FROM ops.data_quality_check WHERE rule = %s",
            ("classify_category_etf_unmapped",),
        )
        (detail,) = cur.fetchone()
    assert written == [
        (stock, "equity", "cn_a"),
        (ids["510300.SH"], "equity", "cn_a"),
        (ids["511010.SH"], "fixed_income", "cn_a"),
        (ids["511880.SH"], "cash", "cn_a"),
    ]
    detail = detail if isinstance(detail, dict) else json.loads(detail)
    assert detail["count"] == 3
    assert detail["by_fund_type"] == {"其他": 1, "股票型": 1, "<no_profile>": 1}
    assert detail["by_channel"] == {"纯境内": 1, "QDII": 1, "<no_profile>": 1}


def test_etf_losing_its_mapping_retires_previous_category(pg_conn, tmp_raw_root):
    """首次为股票型／纯境内写 equity；档案后续变为「其他」、QDII 或删除时，旧分类必须退出。"""
    with pg_conn.cursor() as cur:
        ids = {
            symbol: _instrument(cur, symbol, "etf", "XSHG")
            for symbol in ("510300.SH", "513100.SH", "518880.SH", "510500.SH")
        }
        for iid in ids.values():
            cur.execute(
                "INSERT INTO meta.etf_profile(instrument_id, fund_type, channel, source) "
                "VALUES (%s, '股票型', '纯境内', 'tushare')",
                (iid,),
            )
    pg_conn.commit()
    InstrumentCategoryImporter(pg_conn, IngestContext(paths=tmp_raw_root)).run()

    with pg_conn.cursor() as cur:
        cur.execute(
            "UPDATE meta.etf_profile SET channel = 'QDII' WHERE instrument_id = %s",
            (ids["513100.SH"],),
        )
        cur.execute(
            "UPDATE meta.etf_profile SET fund_type = '其他' WHERE instrument_id = %s",
            (ids["518880.SH"],),
        )
        cur.execute("DELETE FROM meta.etf_profile WHERE instrument_id = %s", (ids["510500.SH"],))
    pg_conn.commit()
    InstrumentCategoryImporter(pg_conn, IngestContext(paths=tmp_raw_root)).run()

    with pg_conn.cursor() as cur:
        cur.execute("SELECT instrument_id FROM classify.instrument_category ORDER BY 1")
        remaining = [r[0] for r in cur.fetchall()]
        cur.execute(
            "SELECT detail FROM ops.data_quality_check WHERE rule = 'classify_category_retired'"
        )
        (detail,) = cur.fetchone()
    assert remaining == [ids["510300.SH"]]
    detail = detail if isinstance(detail, dict) else json.loads(detail)
    assert sorted(detail["sample"]) == sorted(
        ids[s] for s in ("513100.SH", "518880.SH", "510500.SH")
    )
