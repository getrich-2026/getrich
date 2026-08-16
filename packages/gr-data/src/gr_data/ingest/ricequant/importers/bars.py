"""米筐 ingest importers：标的、代码映射、交易日历、日线。"""

from __future__ import annotations

import pandas as pd

from gr_data.common import contracts
from gr_data.ingest.base import BaseImporter
from gr_data.ingest.resolve import resolve_by_symbol_map
from gr_data.ingest.ricequant.adapter import ASSETS, RicequantAdapter, split_obid


PROVIDER = "ricequant"


class InstrumentsImporter(BaseImporter):
    PROVIDER = PROVIDER
    DATASET = "instruments"
    CONTRACT = contracts.INSTRUMENTS
    NOT_NULL_COLUMNS = ("symbol", "asset", "exchange")

    def build(self) -> pd.DataFrame:
        adapter = RicequantAdapter(self.paths)
        rows = []
        for asset in ASSETS:
            df = adapter.read_instruments(asset)
            if df is None or df.empty or "order_book_id" not in df.columns:
                continue
            for _, r in df.iterrows():
                symbol, exchange = split_obid(r["order_book_id"])
                rows.append(
                    {
                        "symbol": symbol,
                        "asset": asset,
                        "exchange": r.get("exchange") or exchange,
                        "name": r.get("symbol"),  # 米筐 symbol 列是中文名
                        "list_date": _date(r.get("listed_date")),
                        "delist_date": _date(r.get("de_listed_date")),
                        "status": str(r.get("status") or "active"),
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
                (list(ASSETS),),
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
    EXCHANGES = ("XSHG", "XSHE")

    def build(self) -> pd.DataFrame:
        adapter = RicequantAdapter(self.paths)
        cal = adapter.read_calendar()
        if cal is None or cal.empty or "trading_day" not in cal.columns:
            return pd.DataFrame(columns=list(self.contract.columns))
        days = sorted(set(pd.to_datetime(cal["trading_day"]).dt.date))
        rows = []
        for exch in self.EXCHANGES:
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
        adapter = RicequantAdapter(self.paths)
        id_map = resolve_by_symbol_map(self.conn, PROVIDER)
        frames = []
        for code in adapter.list_bar_codes(self.ASSET):
            iid = id_map.get(code)
            if iid is None:
                continue
            raw = adapter.read_bars_1d(self.ASSET, code)
            if raw is None or raw.empty:
                continue
            frames.append(self._normalize(raw, iid))
        if not frames:
            return pd.DataFrame(columns=list(self.contract.columns))
        return pd.concat(frames, axis=0, ignore_index=True)

    def _normalize(self, raw: pd.DataFrame, instrument_id: int) -> pd.DataFrame:
        time_col = (
            "date"
            if "date" in raw.columns
            else ("datetime" if "datetime" in raw.columns else raw.columns[0])
        )
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
                "pre_close": raw.get("prev_close"),
                "volume": raw.get("volume"),
                "amount": raw.get("total_turnover"),
                "limit_up": raw.get("limit_up"),
                "limit_down": raw.get("limit_down"),
                "trading_status": None,
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


def _date(val: object):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        d = pd.to_datetime(val)
        if pd.isna(d):
            return None
        return d.date()
    except (ValueError, TypeError):
        return None
