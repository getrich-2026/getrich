"""银河 ingest importers：交易日历、标的、代码映射、日线。

依赖关系（执行顺序）：instruments → symbol_map → calendar → bars_1d。
- instruments 先建立 meta.instruments（产生 instrument_id）。
- symbol_map 把 source_symbol 映射到 instrument_id。
- bars_1d 通过 symbol_map 找 instrument_id 后入库。
"""

from __future__ import annotations

import pandas as pd

from getrich_data.common import contracts
from getrich_data.ingest.base import BaseImporter
from getrich_data.ingest.resolve import resolve_by_symbol_map
from getrich_data.ingest.yinhe.adapter import SECURITY_TYPES, YinheAdapter
from getrich_data.ingest.yinhe.symbols import split_code

PROVIDER = "yinhe"


class InstrumentsImporter(BaseImporter):
    PROVIDER = PROVIDER
    DATASET = "instruments"
    CONTRACT = contracts.INSTRUMENTS
    NOT_NULL_COLUMNS = ("symbol", "asset", "exchange")

    def build(self) -> pd.DataFrame:
        adapter = YinheAdapter(self.paths)
        rows = []
        for asset in SECURITY_TYPES:
            for code in adapter.read_code_list(asset):
                symbol, exchange = split_code(code)
                rows.append(
                    {
                        "symbol": symbol,
                        "asset": asset,
                        "exchange": exchange,
                        "name": None,
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
        # 用 instruments 表反查 instrument_id（symbol == source_symbol）
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT symbol, instrument_id FROM meta.instruments "
                "WHERE asset = ANY(%s)",
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

    # 银河日历给的是 SH 全市场交易日，映射到沪深两所
    EXCHANGES = ("XSHG", "XSHE")

    def build(self) -> pd.DataFrame:
        adapter = YinheAdapter(self.paths)
        cal = adapter.read_calendar("SH")
        if cal is None or cal.empty:
            return pd.DataFrame(columns=list(self.contract.columns))
        days = pd.to_datetime(cal["date"].astype(str), format="%Y%m%d").dt.date
        days = sorted(set(days))
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
        self.CONTRACT = contracts.bar_1d(self.ASSET)
        adapter = YinheAdapter(self.paths)
        id_map = resolve_by_symbol_map(self.conn, PROVIDER)
        frames = []
        for code in adapter.read_code_list(self.ASSET):
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
        # raw 列名取决于银河 SDK；用兜底取列。kline_time 已被 adapter reset 为列。
        time_col = "kline_time" if "kline_time" in raw.columns else raw.columns[0]
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
                "amount": raw.get("amount", raw.get("value")),
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
