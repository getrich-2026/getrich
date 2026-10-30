"""米筐期货合约参数：raw 快照与按结构化键匹配 tushare 身份。"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest
from gr_data.common.parquet import write_parquet
from gr_data.ingest.base import IngestContext, IngestGateError
from gr_data.ingest.ricequant.importers.contracts import FutureContractsImporter
from gr_data.raw.base import RawContext
from gr_data.raw.ricequant.fetchers.contracts import FutureContractsFetcher


def _future(obid: str, underlying: str, exchange: str, **overrides) -> dict:
    row = {
        "order_book_id": obid,
        "underlying_symbol": underlying,
        "exchange": exchange,
        "symbol": f"{underlying}{obid[len(underlying) :]}",
        "listed_date": "2023-01-17",
        "de_listed_date": "2024-01-15",
        "maturity_date": "2024-01-15",
        "contract_multiplier": 5.0,
        "product": "Commodity",
        "margin_rate": 0.08,
        "industry_name": "有色",
        "underlying_order_book_id": "null",
        "type": "Future",
    }
    row.update(overrides)
    return row


class _FakeFutures:
    market = "cn"

    def __init__(self, rows: list[dict], ticks: dict[str, float]) -> None:
        self.rows = rows
        self.ticks = ticks
        self.tick_requests: list[list[str]] = []

    def all_instruments(self, type: str, market: str = "cn") -> pd.DataFrame:
        assert type == "Future"
        return pd.DataFrame(self.rows)

    def get_tick_size(self, order_book_ids: list[str]) -> pd.Series:
        self.tick_requests.append(list(order_book_ids))
        return pd.Series({c: self.ticks[c] for c in order_book_ids if c in self.ticks})


def _ctx(paths) -> RawContext:
    return RawContext(
        paths=paths,
        rate_limit={"sleep_between_requests_sec": 0, "max_retries": 1, "retry_backoff_base_sec": 0},
    )


def test_fetcher_skips_continuous_contracts_for_tick_size(tmp_raw_root):
    """IF88／IF99 没有交易所合约，不查最小变动价位；快照原样保留全部行。"""
    client = _FakeFutures(
        [
            _future("CU2401", "CU", "SHFE"),
            _future("IF88", "IF", "CFFEX", listed_date="0000-00-00"),
            _future("IF2401", "IF", "CFFEX", contract_multiplier=300.0),
        ],
        {"CU2401": 10.0},
    )

    FutureContractsFetcher(client, _ctx(tmp_raw_root)).fetch()

    assert client.tick_requests == [["CU2401", "IF2401"]]
    raw = pd.read_parquet(tmp_raw_root.dataset_file("ricequant", "instruments", "future"))
    tick = pd.read_parquet(tmp_raw_root.dataset_file("ricequant", "instruments", "future_tick"))
    assert len(raw) == 3
    # 源未返回的最小变动价位不补值
    assert tick.to_dict("records") == [{"order_book_id": "CU2401", "tick_size": 10.0}]


def _tushare_future(cur, symbol: str, exchange: str, product: str, month: str, listed: date) -> int:
    cur.execute(
        "INSERT INTO meta.instruments(symbol, asset, exchange, list_date) "
        "VALUES (%s, 'future', %s, %s) RETURNING instrument_id",
        (symbol, exchange, listed),
    )
    iid = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO meta.future_profile(instrument_id, product_code, delivery_month, source) "
        "VALUES (%s, %s, %s, 'tushare')",
        (iid, product, month),
    )
    return iid


def _write_raw(paths, rows: list[dict], ticks: dict[str, float]) -> None:
    write_parquet(pd.DataFrame(rows), paths.dataset_file("ricequant", "instruments", "future"))
    write_parquet(
        pd.DataFrame({"order_book_id": list(ticks), "tick_size": list(ticks.values())}),
        paths.dataset_file("ricequant", "instruments", "future_tick"),
    )


def test_importer_matches_by_exchange_product_and_month(pg_conn, tmp_raw_root):
    """郑商所代码位数两边不同也能对上；冲突、未匹配、未知交易所都不写并留痕。"""
    with pg_conn.cursor() as cur:
        cu = _tushare_future(cur, "CU2401.SHF", "SHFE", "CU", "202401", date(2023, 1, 17))
        # tushare 郑商所代码为 3 位年月，米筐补齐为 4 位：不改写代码，按结构化键匹配
        ap = _tushare_future(cur, "AP405.ZCE", "CZCE", "AP", "202405", date(2023, 5, 16))
        idx = _tushare_future(cur, "IF2401.CFX", "CFFEX", "IF", "202401", date(2023, 5, 22))
        al = _tushare_future(cur, "AL2401.SHF", "SHFE", "AL", "202401", date(2023, 1, 17))
        wt = _tushare_future(cur, "WT9903.ZCE", "CZCE", "WT", "199903", date(1999, 1, 4))
    pg_conn.commit()
    _write_raw(
        tmp_raw_root,
        [
            _future("CU2401", "CU", "SHFE"),
            _future("AP2405", "AP", "CZCE", listed_date="2023-05-16", contract_multiplier=10.0),
            _future(
                "IF2401",
                "IF",
                "CFFEX",
                listed_date="2023-05-22",
                contract_multiplier=300.0,
                product="Index",
                underlying_order_book_id="000300.XSHG",
            ),
            _future("AL2401", "AL", "SHFE", listed_date="2023-01-18"),  # 上市日两源不一致
            # 1999 年合约：两位年份须按上市年份补成 1999，不能当成 2099
            _future("WT9903", "WT", "CZCE", listed_date="1999-01-04", contract_multiplier=10.0),
            _future("ZZ0001", "ZZ", "SHFE", listed_date=None),  # 无上市日，世纪无法确定
            _future("ZN2401", "ZN", "SHFE"),  # tushare 无此身份
            _future("XX2401", "XX", "NYMEX"),  # 未知交易所
            _future("CU88", "CU", "SHFE", listed_date="0000-00-00"),  # 连续合约
        ],
        {"CU2401": 10.0, "AP2405": 1.0, "IF2401": 0.2, "AL2401": 5.0, "WT9903": 1.0},
    )

    result = FutureContractsImporter(pg_conn, IngestContext(paths=tmp_raw_root)).run()

    assert result.rows_written == 5
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT instrument_id, multiplier, price_tick, product, underlying_code, source "
            "FROM meta.future_contracts ORDER BY instrument_id"
        )
        rows = [(r[0], float(r[1]), float(r[2]), r[3], r[4], r[5]) for r in cur.fetchall()]
        cur.execute("SELECT rule, detail FROM ops.data_quality_check ORDER BY rule")
        checks = {rule: (d if isinstance(d, dict) else json.loads(d)) for rule, d in cur.fetchall()}
        cur.execute(
            "SELECT provider FROM ops.table_ownership WHERE target = 'meta.future_contracts'"
        )
        owner = cur.fetchone()
    assert rows == [
        (cu, 5.0, 10.0, "Commodity", None, "ricequant"),
        (ap, 10.0, 1.0, "Commodity", None, "ricequant"),
        (idx, 300.0, 0.2, "Index", "000300.XSHG", "ricequant"),
        # 身份键唯一，上市日两源不一致照常写入，只留对账记录
        (al, 5.0, 5.0, "Commodity", None, "ricequant"),
        (wt, 10.0, 1.0, "Commodity", None, "ricequant"),
    ]
    assert {rule: d["sample"] for rule, d in checks.items()} == {
        "future_contracts_ambiguous_year": ["ZZ0001"],
        "future_contracts_list_date_mismatch": ["AL2401"],
        "future_contracts_unknown_exchange": ["XX2401"],
        "future_contracts_unmatched": ["ZN2401"],
    }
    assert owner == ("ricequant",)


def test_importer_skips_ambiguous_keys(pg_conn, tmp_raw_root, monkeypatch):
    """同一 (交易所, 品种, 交割年月) 在 tushare 侧有两条身份时无法判断，两条都不写。"""
    with pg_conn.cursor() as cur:
        _tushare_future(cur, "CU2401.SHF", "SHFE", "CU", "202401", date(2023, 1, 17))
        _tushare_future(cur, "CU2401X.SHF", "SHFE", "CU", "202401", date(2023, 1, 17))
        _tushare_future(cur, "AL2401.SHF", "SHFE", "AL", "202401", date(2023, 1, 17))
    pg_conn.commit()
    _write_raw(
        tmp_raw_root,
        [_future("CU2401", "CU", "SHFE"), _future("AL2401", "AL", "SHFE")],
        {"CU2401": 10.0, "AL2401": 5.0},
    )

    imp = FutureContractsImporter(pg_conn, IngestContext(paths=tmp_raw_root))
    out = imp.build()

    assert out["price_tick"].tolist() == [5.0]  # 只剩无歧义的 AL2401
    with pg_conn.cursor() as cur:
        cur.execute("SELECT rule, detail->'sample' FROM ops.data_quality_check")
        assert cur.fetchall() == [("future_contracts_ambiguous_key", ["CU2401"])]


def test_importer_fails_loudly_when_nothing_matches(pg_conn, tmp_raw_root):
    """全部对不上说明匹配规则或源数据出了问题：质量门禁失败，不当作成功的空写入。"""
    _write_raw(tmp_raw_root, [_future("CU2401", "CU", "SHFE")], {"CU2401": 10.0})

    with pytest.raises(IngestGateError, match="空数据集"):
        FutureContractsImporter(pg_conn, IngestContext(paths=tmp_raw_root)).run()


def test_importer_requires_both_raw_files(tmp_raw_root):
    """缺快照或缺最小变动价位文件时硬失败，不写半套参数。"""
    write_parquet(
        pd.DataFrame([_future("CU2401", "CU", "SHFE")]),
        tmp_raw_root.dataset_file("ricequant", "instruments", "future"),
    )
    imp = FutureContractsImporter(conn=None, ctx=IngestContext(paths=tmp_raw_root))  # type: ignore[arg-type]

    with pytest.raises(IngestGateError, match="tick"):
        imp.build()
