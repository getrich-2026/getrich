"""Tushare ingest importers：标的、代码映射、交易日历。"""

from __future__ import annotations

import pandas as pd

from gr_data.common import contracts
from gr_data.ingest.base import BaseImporter
from gr_data.ingest.tushare.adapter import (
    ASSETS,
    CALENDAR_EXCHANGE_MAP,
    CALENDAR_EXCHANGES,
    TushareAdapter,
)
from gr_data.ingest.tushare.symbols import split_ts_code


PROVIDER = "tushare"

# Tushare list_status → canonical status
LIST_STATUS_MAP = {"L": "active", "D": "delisted", "P": "suspended"}


def parse_date(value: object) -> object:
    """解析 Tushare 的 ``YYYYMMDD`` 日期。空值返回 None，非法值抛错。

    非法日期**不静默丢弃**——那会让缺失伪装成正常空值（见 CLAUDE.md 数据完整性铁律）。
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text or text in ("None", "nan", "NaT", "0", "00000000"):
        return None
    parsed = pd.to_datetime(text, format="%Y%m%d", errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"非法的 Tushare 日期值: {value!r}")
    return parsed.date()


def _require(df: pd.DataFrame, columns: set[str], source: str) -> None:
    missing = columns - set(df.columns)
    if missing:
        raise ValueError(f"{source} 缺少字段: {sorted(missing)}")


def _clean_codes(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """去空白、校验非空、按 ts_code 去重（保留最后一条）。"""
    out = df.copy()
    out["ts_code"] = out["ts_code"].astype(str).str.strip()
    if out["ts_code"].eq("").any():
        raise ValueError(f"{source} 含空 ts_code")
    return out.drop_duplicates(subset=["ts_code"], keep="last")


class InstrumentsImporter(BaseImporter):
    """股票 + 指数 + 期货标的 → meta.instruments。"""

    PROVIDER = PROVIDER
    DATASET = "instruments"
    CONTRACT = contracts.INSTRUMENTS
    NOT_NULL_COLUMNS = ("symbol", "asset", "exchange")

    def build(self) -> pd.DataFrame:
        adapter = TushareAdapter(self.paths)
        frames = []
        for asset in ASSETS:
            raw = adapter.read_instruments(asset)
            if raw is None or raw.empty:
                self.log.warning("instruments[%s] 无 raw 数据，跳过", asset)
                continue
            frames.append(getattr(self, f"_build_{asset}")(raw))
        if not frames:
            return pd.DataFrame(columns=list(self.contract.columns))
        out = pd.concat(frames, axis=0, ignore_index=True)
        # 同一 (asset, exchange, symbol) 只保留一条，避免 upsert 内部键冲突
        return out.drop_duplicates(
            subset=list(self.contract.conflict_keys), keep="last"
        ).reset_index(drop=True)

    def _build_stock(self, raw: pd.DataFrame) -> pd.DataFrame:
        _require(raw, {"ts_code", "name", "list_status", "list_date", "delist_date"}, "stock_basic")
        r = _clean_codes(raw, "stock_basic")
        return pd.DataFrame(
            {
                "symbol": r["ts_code"],
                "asset": "stock",
                "exchange": [split_ts_code(c)[1] for c in r["ts_code"]],
                "name": r["name"].where(r["name"].notna(), None),
                "list_date": r["list_date"].map(parse_date),
                "delist_date": r["delist_date"].map(parse_date),
                "status": r["list_status"].map(
                    lambda s: LIST_STATUS_MAP.get(str(s).strip(), "active")
                ),
            }
        )[list(self.contract.columns)]

    def _build_index(self, raw: pd.DataFrame) -> pd.DataFrame:
        _require(raw, {"ts_code", "name", "list_date", "exp_date"}, "index_basic")
        r = _clean_codes(raw, "index_basic")
        exp = r["exp_date"].map(parse_date)
        return pd.DataFrame(
            {
                "symbol": r["ts_code"],
                "asset": "index",
                "exchange": [split_ts_code(c)[1] for c in r["ts_code"]],
                "name": r["name"].where(r["name"].notna(), None),
                "list_date": r["list_date"].map(parse_date),
                # 指数用 exp_date 表达终止日；有值即视为已退市
                "delist_date": exp,
                "status": ["delisted" if d is not None else "active" for d in exp],
            }
        )[list(self.contract.columns)]

    def _build_future(self, raw: pd.DataFrame) -> pd.DataFrame:
        _require(raw, {"ts_code", "name", "list_date", "delist_date"}, "fut_basic")
        r = _clean_codes(raw, "fut_basic")
        return pd.DataFrame(
            {
                "symbol": r["ts_code"],
                "asset": "future",
                "exchange": [split_ts_code(c)[1] for c in r["ts_code"]],
                "name": r["name"].where(r["name"].notna(), None),
                "list_date": r["list_date"].map(parse_date),
                "delist_date": r["delist_date"].map(parse_date),
                "status": "active",
            }
        )[list(self.contract.columns)]


class SymbolMapImporter(BaseImporter):
    """meta.instruments → meta.symbol_map，供 bars importer 解析 instrument_id。"""

    PROVIDER = PROVIDER
    DATASET = "symbol_map"
    CONTRACT = contracts.SYMBOL_MAP
    NOT_NULL_COLUMNS = ("instrument_id", "source", "source_symbol")

    def build(self) -> pd.DataFrame:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT symbol, instrument_id FROM meta.instruments WHERE asset = ANY(%s)",
                (list(ASSETS),),
            )
            rows = [
                {"instrument_id": int(iid), "source": PROVIDER, "source_symbol": sym}
                for sym, iid in cur.fetchall()
            ]
        return pd.DataFrame(rows, columns=list(self.contract.columns))


class CalendarImporter(BaseImporter):
    """trade_cal → meta.trading_calendar，并推导 next_trading_day。"""

    PROVIDER = PROVIDER
    DATASET = "calendar"
    CONTRACT = contracts.TRADING_CALENDAR
    NOT_NULL_COLUMNS = ("exchange", "trading_day")

    def build(self) -> pd.DataFrame:
        adapter = TushareAdapter(self.paths)
        frames = []
        for exchange in CALENDAR_EXCHANGES:
            raw = adapter.read_calendar(exchange)
            if raw is None or raw.empty:
                self.log.warning("calendar[%s] 无 raw 数据，跳过", exchange)
                continue
            frames.append(self._build_one(raw, CALENDAR_EXCHANGE_MAP[exchange]))
        if not frames:
            return pd.DataFrame(columns=list(self.contract.columns))
        return pd.concat(frames, axis=0, ignore_index=True)

    def _build_one(self, raw: pd.DataFrame, exchange: str) -> pd.DataFrame:
        _require(raw, {"cal_date", "is_open"}, "trade_cal")
        r = raw.drop_duplicates(subset=["cal_date"], keep="last").copy()
        r["trading_day"] = r["cal_date"].map(parse_date)
        if r["trading_day"].isna().any():
            raise ValueError("trade_cal 含非法 cal_date")
        r["is_open"] = (
            pd.to_numeric(r["is_open"], errors="coerce").fillna(0).astype(int).astype(bool)
        )
        r = r.sort_values("trading_day").reset_index(drop=True)

        prev_col = (
            r["pretrade_date"].map(parse_date)
            if "pretrade_date" in r.columns
            else pd.Series([None] * len(r))
        )

        # next_trading_day：自后向前扫，记住「右侧最近的开市日」。
        # 区间尾部无后继时保留 NULL，不猜测（fetcher 多取一年缓冲以缩小该区域）。
        next_days: list[object] = [None] * len(r)
        seen: object = None
        for i in range(len(r) - 1, -1, -1):
            next_days[i] = seen
            if r.at[i, "is_open"]:
                seen = r.at[i, "trading_day"]

        return pd.DataFrame(
            {
                "exchange": exchange,
                "trading_day": r["trading_day"],
                "is_open": r["is_open"],
                # A 股股票市场无夜盘；期货夜盘不由 trade_cal 表达
                "has_night": False,
                "prev_trading_day": prev_col,
                "next_trading_day": next_days,
            }
        )[list(self.contract.columns)]
