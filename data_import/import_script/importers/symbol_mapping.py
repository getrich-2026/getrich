from __future__ import annotations

import pandas as pd

from ..importer import BaseImporter, ImportContext, ResolvedMode


SECURITY_TYPES = [
    "EXTRA_STOCK_A_SH_SZ",
    "EXTRA_ETF",
    "EXTRA_IDNEX_A_SH_SZ",
]


class SymbolMappingImporter(BaseImporter):
    name = "symbol_mapping"
    target_table = "re.symbol_mapping"
    primary_keys = ("provider", "symbol")
    full_replace = True

    def stream_frames(self, ctx: ImportContext, mode: ResolvedMode, since: object | None):
        codes: set[str] = set()
        for security_type in SECURITY_TYPES:
            codes.update(ctx.store.hist_codes(security_type))
        if not codes:
            return
        df = pd.DataFrame({"symbol": sorted(codes)})
        df["provider"] = ctx.config.provider
        df["mapped_symbol"] = df["symbol"]
        yield df

