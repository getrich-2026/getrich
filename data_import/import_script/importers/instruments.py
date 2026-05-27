from __future__ import annotations

import pandas as pd

from ..importer import BaseImporter, ImportContext, ResolvedMode
from ..utils import exchange_from_code


class _HistCodeInstrumentImporter(BaseImporter):
    security_type = ""
    instrument_type = ""
    full_replace = True

    def base_frame(self, ctx: ImportContext) -> pd.DataFrame:
        codes = ctx.store.hist_codes(self.security_type)
        df = pd.DataFrame({"order_book_id": codes})
        if df.empty:
            return df
        df["symbol"] = df["order_book_id"]
        df["type"] = self.instrument_type
        df["exchange"] = df["order_book_id"].map(exchange_from_code)
        df["status"] = "UNKNOWN"
        df["trading_code"] = df["order_book_id"]
        return df

    def stream_frames(self, ctx: ImportContext, mode: ResolvedMode, since: object | None):
        df = self.base_frame(ctx)
        if not df.empty:
            yield df


class InstrumentsCsImporter(_HistCodeInstrumentImporter):
    name = "rq_instruments_cs"
    target_table = "rq.instruments_cs"
    primary_keys = ("order_book_id",)
    security_type = "EXTRA_STOCK_A_SH_SZ"
    instrument_type = "CS"


class InstrumentsEtfImporter(_HistCodeInstrumentImporter):
    name = "rq_instruments_etf"
    target_table = "rq.instruments_etf"
    primary_keys = ("order_book_id",)
    security_type = "EXTRA_ETF"
    instrument_type = "ETF"


class InstrumentsIndxImporter(_HistCodeInstrumentImporter):
    name = "rq_instruments_indx"
    target_table = "rq.instruments_indx"
    primary_keys = ("order_book_id",)
    security_type = "EXTRA_IDNEX_A_SH_SZ"
    instrument_type = "INDX"

