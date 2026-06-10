"""华泰 INSIGHT ingest importers：标的、代码映射、交易日历、日线。"""

from __future__ import annotations

import pandas as pd

from getrich_data.common import contracts
from getrich_data.ingest.base import BaseImporter
from getrich_data.ingest.insight.adapter import (
    SECURITY_TYPES,
    InsightAdapter,
    split_htsc,
)
from getrich_data.ingest.resolve import resolve_by_symbol_map

PROVIDER = "insight"


class InstrumentsImporter(BaseImporter):
    PROVIDER = PROVIDER
    DATASET = "instruments"
    CONTRACT = contracts.INSTRUMENTS
    NOT_NULL_COLUMNS = ("symbol", "asset", "exchange")

    def build(self) -> pd.DataFrame:
        adapter = InsightAdapter(self.paths)
        rows = []
        for asset in SECURITY_TYPES:
            df = adapter.read_basic_info(asset)
            if df is None or df.empty or "htsc_code" not in df.columns:
                continue
            for _, r in df.iterrows():
                symbol, exchange = split_htsc(r["htsc_code"])
                rows.append(
                    {
                        "symbol": symbol,
                        "asset": asset,
                        "exchange": exchange,
                        "name": r.get("security_name") or r.get("name"),
                        "list_date": None,
                        "delist_date": None,
                        "status": "active",
                    }
                )
        return pd.DataFrame(rows, columns=list(self.contract.columns))


class SymbolMapImporter(BaseImporter):
    PROVIDER = PROVIDER
    DATASET = "symbol_map"
    CONTRACT = contracts.SYMBOL_MAP
    NOT_NULL_COLUMNS = ("instrument_id", "source", "source_symbol")

    def build(self) -> pd.DataFrame:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT symbol, instrument_id FROM meta.instruments WHERE asset = ANY(%s)",
                (list(SECURITY_TYPES.keys()),),
            )
            sym_to_id = {r[0]: int(r[1]) for r in cur.fetchall()}
        rows = [
            {"instrument_id": iid, "source": PROVIDER, "source_symbol": sym}
            for sym, iid in sym_to_id.items()
        ]
        return pd.DataFrame(rows, columns=list(self.contract.columns))


class CalendarImporter(BaseImporter):
    PROVIDER = PROVIDER
    DATASET = "calendar"
    CONTRACT = contracts.TRADING_CALENDAR
    NOT_NULL_COLUMNS = ("exchange", "trading_day")
    EXCHANGE_MAP = {"XSHG": "XSHG", "XSHE": "XSHE"}

    def build(self) -> pd.DataFrame:
        adapter = InsightAdapter(self.paths)
        rows = []
        for exch in ("XSHG", "XSHE"):
            df = adapter.read_trading_days(exch)
            if df is None or df.empty:
                continue
            col = "TradingDate" if "TradingDate" in df.columns else df.columns[0]
            # 只取交易日（IfTradingDay 为真时）
            if "IfTradingDay" in df.columns:
                df = df[df["IfTradingDay"].astype(bool)]
            days = sorted(set(pd.to_datetime(df[col]).dt.date))
            for i, d in enumerate(days):
                rows.append(
                    {
                        "exchange": exch,
                        "trading_day": d,
                        "is_open": True,
                        "has_night": False,
                        "prev_trading_day": days[i - 1] if i > 0 else None,
                        "next_trading_day": days[i + 1] if i < len(days) - 1 else None,
                    }
                )
        return pd.DataFrame(rows, columns=list(self.contract.columns))


class _BarsImporter(BaseImporter):
    PROVIDER = PROVIDER
    ASSET = "stock"
    NOT_NULL_COLUMNS = ("instrument_id", "dt", "trading_day")

    def build(self) -> pd.DataFrame:
        adapter = InsightAdapter(self.paths)
        id_map = resolve_by_symbol_map(self.conn, PROVIDER)
        frames = []
        # 遍历该 asset 的代码（从 basic_info 取）
        info = adapter.read_basic_info(self.ASSET)
        codes = (
            [str(c) for c in info["htsc_code"].tolist()]
            if info is not None and "htsc_code" in info.columns
            else []
        )
        for code in codes:
            iid = id_map.get(code)
            if iid is None:
                continue
            raw = adapter.read_kline_day(code)
            if raw is None or raw.empty:
                continue
            frames.append(self._normalize(raw, iid))
        if not frames:
            return pd.DataFrame(columns=list(self.contract.columns))
        return pd.concat(frames, axis=0, ignore_index=True)

    def _normalize(self, raw: pd.DataFrame, instrument_id: int) -> pd.DataFrame:
        time_col = "time" if "time" in raw.columns else raw.columns[0]
        ts = pd.to_datetime(raw[time_col])
        out = pd.DataFrame(
            {
                "instrument_id": instrument_id,
                "dt": ts.dt.date,
                "trading_day": ts.dt.date,
                "open": raw.get("open"),
                "high": raw.get("high"),
                "low": raw.get("low"),
                "close": raw.get("close"),
                "pre_close": raw.get("pre_close"),
                "volume": raw.get("volume"),
                "amount": raw.get("value", raw.get("amount")),
                "limit_up": raw.get("limit_up"),
                "limit_down": raw.get("limit_down"),
                "trading_status": raw.get("trading_status"),
                "adj_factor": 1.0,
                "source": PROVIDER,
            }
        )
        return out[list(self.contract.columns)]


class StockBars1dImporter(_BarsImporter):
    DATASET = "stock_bar_1d"
    ASSET = "stock"
    CONTRACT = contracts.bar_1d("stock")


class EtfBars1dImporter(_BarsImporter):
    DATASET = "etf_bar_1d"
    ASSET = "etf"
    CONTRACT = contracts.bar_1d("etf")


class IndexBars1dImporter(_BarsImporter):
    DATASET = "index_bar_1d"
    ASSET = "index"
    CONTRACT = contracts.bar_1d("index")
