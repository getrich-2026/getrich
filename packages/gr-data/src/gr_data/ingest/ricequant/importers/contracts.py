"""米筐期货合约快照 → meta.future_contracts。

期货身份由 tushare 登记（meta.instruments + meta.future_profile），这里只补米筐独有的
合约乘数、最小变动价位等参数。两边代码格式不同（米筐无交易所后缀、郑商所年份补齐为
4 位），**不改写代码字符串去对齐**，而是按两边各自的结构化字段匹配：

    米筐 (exchange, underlying_symbol, 代码中的 YYMM 按上市年份定世纪)
    tushare (meta.instruments.exchange, future_profile.product_code, future_profile.delivery_month)

代码只有两位年份，1999 年的 ``AL9901`` 与 2099 年同形，世纪必须由米筐上市日确定
（交割年落在上市当年至其后 10 年内且唯一）。键在任一侧不唯一、世纪无法唯一确定或
匹配不到时都不写，记入 ops.data_quality_check；写错一行（乘数错位）远比少一行危害大。

两源对老合约的上市日记录不一致（2026-10-30 实测上期所 2003–2010 年合约为主，相差中位
13 天）不影响身份判定：上述键在交易所规则下唯一确定一份合约，照常写入并记
``future_contracts_list_date_mismatch`` 留作对账。用户确定期货上市日暂以米筐为准，
米筐 ``listed_date`` 写入本表 ``list_date``；meta.instruments.list_date 仍是 tushare 原值。
"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd

from gr_data.common import contracts
from gr_data.common.parquet import read_parquet_strict
from gr_data.ingest.base import BaseImporter, IngestGateError
from gr_data.ingest.ricequant.adapter import RicequantAdapter
from gr_data.raw.ricequant.fetchers.contracts import REGULAR_FUTURE


PROVIDER = "ricequant"

#: 米筐 exchange 取值 → canonical 交易所码（meta.instruments 对期货存 SHFE／DCE／…）。
#: 米筐合约文档列出的取值与 canonical 码同名；不在表内的交易所整行跳过并留痕。
_CANONICAL_EXCHANGES = frozenset({"SHFE", "DCE", "CZCE", "CFFEX", "INE", "GFEX"})

_REQUIRED = (
    "order_book_id",
    "underlying_symbol",
    "exchange",
    "listed_date",
    "contract_multiplier",
    "product",
    "margin_rate",
    "industry_name",
    "underlying_order_book_id",
)


def _rq_date(value: object) -> date | None:
    """米筐日期：``YYYY-MM-DD`` 字符串或时间戳；``0000-00-00`` 表示无。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text or text.startswith("0000"):
        return None
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        raise IngestGateError(f"Invalid RiceQuant date value={value!r}")
    return parsed.date()


def _delivery_month(yymm: str, listed: date | None) -> str | None:
    """两位年份按上市年份补世纪：交割年须在上市当年至其后 10 年内且唯一，否则返回 None。"""
    if listed is None:
        return None
    yy, mm = int(yymm[:2]), yymm[2:]
    years = [c + yy for c in (1900, 2000) if listed.year <= c + yy <= listed.year + 10]
    return f"{years[0]}{mm}" if len(years) == 1 else None


def _positive(series: pd.Series, field: str, *, allow_zero: bool = False) -> pd.Series:
    """严格转数值；缺失保持 None，非法或非正值硬失败。"""
    parsed = pd.to_numeric(series, errors="coerce")
    nonpositive = parsed.lt(0) if allow_zero else parsed.le(0)
    bad = series.notna() & (parsed.isna() | nonpositive)
    if bad.any():
        raise IngestGateError(f"Invalid RiceQuant {field} samples={series[bad].head(5).tolist()}")
    return parsed.astype(object).where(parsed.notna(), None)


class FutureContractsImporter(BaseImporter):
    PROVIDER = PROVIDER
    DATASET = "future_contracts"
    CONTRACT = contracts.FUTURE_CONTRACTS
    NOT_NULL_COLUMNS = ("instrument_id", "source")
    STRICT_QUALITY = True

    def build(self) -> pd.DataFrame:
        raw = RicequantAdapter(self.paths).read_instruments("future")
        tick = read_parquet_strict(self.paths.dataset_file(PROVIDER, "instruments", "future_tick"))
        if raw is None or raw.empty or tick is None:
            raise IngestGateError("Missing RiceQuant future instruments or tick raw")
        missing = set(_REQUIRED) - set(raw.columns)
        if missing or not {"order_book_id", "tick_size"} <= set(tick.columns):
            raise IngestGateError(f"RiceQuant future raw lacks columns {sorted(missing)}")

        rq = raw.copy()
        rq["order_book_id"] = rq["order_book_id"].astype(str).str.strip()
        parts = rq["order_book_id"].str.extract(REGULAR_FUTURE)
        # 主力／指数连续合约没有交易所合约可对应；代码前缀须与品种一致才算普通合约。
        regular = parts[0].notna() & parts[0].eq(rq["underlying_symbol"].astype(str))
        rq = rq[regular].copy()
        rq["delivery_month"] = [
            _delivery_month(yymm, _rq_date(listed))
            for yymm, listed in zip(parts.loc[regular, 1], rq["listed_date"], strict=True)
        ]
        undetermined = rq["delivery_month"].isna()
        if undetermined.any():
            self._record("future_contracts_ambiguous_year", rq[undetermined])
            rq = rq[~undetermined]
        rq["exchange"] = rq["exchange"].astype(str).str.strip()
        unknown_exchange = ~rq["exchange"].isin(_CANONICAL_EXCHANGES)
        if unknown_exchange.any():
            self._record("future_contracts_unknown_exchange", rq[unknown_exchange])
            rq = rq[~unknown_exchange]
        rq["key"] = list(
            zip(rq["exchange"], rq["underlying_symbol"], rq["delivery_month"], strict=True)
        )

        ts = self._tushare_identities()
        rq_dup = rq["key"].duplicated(keep=False)
        ts_dup = ts["key"].duplicated(keep=False)
        ambiguous = set(rq.loc[rq_dup, "key"]) | set(ts.loc[ts_dup, "key"])
        if ambiguous:
            self._record("future_contracts_ambiguous_key", rq[rq["key"].isin(ambiguous)])
        rq = rq[~rq["key"].isin(ambiguous)]
        ts = ts[~ts["key"].isin(ambiguous)]

        merged = rq.merge(ts, on="key", how="left", validate="one_to_one")
        unmatched = merged["instrument_id"].isna()
        if unmatched.any():
            self._record("future_contracts_unmatched", merged[unmatched])
        merged = merged[~unmatched]
        rq_listed = merged["listed_date"].map(_rq_date)
        conflict = (
            rq_listed.notna() & merged["list_date"].notna() & rq_listed.ne(merged["list_date"])
        )
        if conflict.any():
            # 身份已由唯一键确定；上市日差异是两源记录口径不同，写入并留痕供对账。
            self._record("future_contracts_list_date_mismatch", merged[conflict])

        listed = merged["listed_date"].map(_rq_date)
        tick_map = dict(zip(tick["order_book_id"].astype(str), tick["tick_size"], strict=True))
        underlying = merged["underlying_order_book_id"].astype(object)
        out = pd.DataFrame(
            {
                "instrument_id": merged["instrument_id"].astype("int64"),
                "multiplier": _positive(merged["contract_multiplier"], "contract_multiplier"),
                "price_tick": _positive(merged["order_book_id"].map(tick_map), "tick_size"),
                "product": merged["product"].where(merged["product"].notna(), None),
                "margin_rate": _positive(merged["margin_rate"], "margin_rate", allow_zero=True),
                "industry_name": merged["industry_name"].where(
                    merged["industry_name"].notna(), None
                ),
                # 米筐对非股指期货给字符串 'null'，不当作代码入库。
                "underlying_code": underlying.where(
                    underlying.notna() & ~underlying.astype(str).isin(["null", ""]), None
                ),
                "list_date": listed.astype(object).where(listed.notna(), None),
                "source": PROVIDER,
            }
        )
        return out[list(self.contract.columns)].reset_index(drop=True)

    def _tushare_identities(self) -> pd.DataFrame:
        """tushare 登记的普通期货合约：(交易所, 品种, 交割年月) → instrument_id、上市日。"""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT i.instrument_id, i.exchange, p.product_code, p.delivery_month, i.list_date "
                "FROM meta.instruments i JOIN meta.future_profile p USING (instrument_id) "
                "WHERE i.asset = 'future' AND p.product_code IS NOT NULL "
                "AND p.delivery_month IS NOT NULL"
            )
            rows = cur.fetchall()
        ts = pd.DataFrame(
            rows,
            columns=["instrument_id", "exchange", "product_code", "delivery_month", "list_date"],
        )
        ts["key"] = list(zip(ts["exchange"], ts["product_code"], ts["delivery_month"], strict=True))
        return ts[["key", "instrument_id", "list_date"]]

    def _record(self, rule: str, skipped: pd.DataFrame) -> None:
        detail = {
            "count": int(len(skipped)),
            "sample": skipped["order_book_id"].head(20).tolist(),
        }
        self.log.warning("%s skipped=%d", rule, detail["count"])
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ops.data_quality_check (rule, severity, detail) VALUES (%s, %s, %s)",
                (rule, "warn", json.dumps(detail, ensure_ascii=False)),
            )
