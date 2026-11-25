"""抓取单股分红全历史或全市场退市名录，直到空页才发布覆盖凭据。"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx
import polars as pl

from gr_data.common.paths import RawPaths


_FIELDS = (
    "ts_code,end_date,ann_date,div_proc,stk_div,stk_bo_rate,stk_co_rate,cash_div,"
    "cash_div_tax,record_date,ex_date,pay_date,div_listdate,imp_ann_date,base_date,base_share"
)
_DELIST_FIELDS = "ts_code,name,exchange,list_status,list_date,delist_date"


def capture_dividend(client: httpx.Client, token: str, symbol: str, paths: RawPaths) -> Path:
    """抓取单股全部方案并保留原字段。网络或分页失败时不发布覆盖证明。"""
    if not token.strip() or not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", symbol):
        raise ValueError("Expected a configured token and a canonical Tushare stock code")
    return _capture(
        client,
        token,
        "dividend",
        {"ts_code": symbol},
        _FIELDS,
        paths.dataset_dir("tushare", "dividend") / symbol,
        {"scope": "symbol_full_history", "symbol": symbol},
    )


def capture_delistings(client: httpx.Client, token: str, paths: RawPaths) -> Path:
    """抓取仅含已退市证券的完整目录，用于明确负证据与退市截断。"""
    if not token.strip():
        raise ValueError("Expected a configured Tushare token")
    return _capture(
        client,
        token,
        "stock_basic",
        {"list_status": "D"},
        _DELIST_FIELDS,
        paths.dataset_dir("tushare", "stock_basic") / "delisted",
        {"scope": "all_delisted", "list_status": "D"},
    )


def _capture(
    client: httpx.Client,
    token: str,
    dataset: Literal["dividend", "stock_basic"],
    params: dict[str, str],
    fields: str,
    directory: Path,
    scope: dict[str, str],
) -> Path:
    columns = fields.split(",")
    items: list[list] = []
    seen: set[tuple] = set()
    while True:
        try:
            response = client.post(
                f"https://api.waditu.com/dataapi/{dataset}",
                json={
                    "api_name": dataset,
                    "token": token,
                    "fields": fields,
                    "params": {**params, "limit": 100, "offset": len(items)},
                },
                timeout=30,
                follow_redirects=False,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(f"Tushare capture failed for {dataset}") from exc
        if payload["code"] != 0 or payload["data"]["fields"] != columns:
            raise ValueError(f"Tushare rejected query or changed fields: {dataset}")
        page = payload["data"]["items"]
        if not isinstance(page, list) or len(page) > 100:
            raise ValueError(f"Invalid Tushare response page: {dataset}")
        if not page:
            break
        for row in page:
            if (
                len(row) != len(columns)
                or (dataset == "dividend" and row[0] != params["ts_code"])
                or (dataset == "stock_basic" and row[3] != "D")
                or tuple(row) in seen
            ):
                raise ValueError(f"Inconsistent Tushare pagination for {dataset}")
            seen.add(tuple(row))
        items.extend(page)
        time.sleep(1.5)
    observed = datetime.now(timezone.utc)
    frame = pl.DataFrame(items, schema=columns, orient="row", infer_schema_length=None)
    if dataset == "stock_basic" and (
        frame.is_empty() or frame["ts_code"].n_unique() != frame.height
    ):
        raise ValueError("Incomplete or duplicate delisted universe")
    directory.mkdir(parents=True, exist_ok=True)
    # 每次成功请求保留独立快照；凭据最后发布，读端校验文件摘要。
    path = directory / f"{observed:%Y%m%dT%H%M%S%fZ}-{uuid4().hex}.parquet"
    temporary = path.with_name(f"{path.name}.tmp-{uuid4().hex}")
    receipt = path.with_suffix(".coverage.json")
    try:
        frame.write_parquet(temporary, compression="zstd")
        digest = sha256(temporary.read_bytes()).hexdigest()
        temporary.replace(path)
        proof = {
            "version": 1,
            "source": "tushare",
            "dataset": dataset,
            **scope,
            "rows": len(items),
            "empty_page_offset": len(items),
            "observed_at": observed.isoformat(),
            "sha256": digest,
        }
        temporary.write_text(json.dumps(proof, sort_keys=True), encoding="utf-8")
        temporary.replace(receipt)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def main() -> None:
    """仓外 raw 根目录与凭据来自项目环境快照。"""
    import argparse

    from gr_tools.config import load_environment

    parser = argparse.ArgumentParser(description=__doc__)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("symbol", nargs="?")
    selector.add_argument("--delisted", action="store_true", help="采集 stock_basic(D) 全集。")
    args = parser.parse_args()
    env = load_environment().values
    with httpx.Client() as client:
        paths = RawPaths(env["RAW_PARQUET_ROOT"])
        token = env["TUSHARE_TOKEN"]
        path = (
            capture_delistings(client, token, paths)
            if args.delisted
            else capture_dividend(client, token, args.symbol, paths)
        )
        print(path)


if __name__ == "__main__":
    main()
