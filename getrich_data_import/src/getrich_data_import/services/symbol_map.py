from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection


@dataclass(frozen=True)
class SymbolMapping:
    instrument_id: int
    source: str
    source_symbol: str
    symbol: str
    asset: str
    exchange: str


class SymbolMapService:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def resolve_one(self, *, source: str, source_symbol: str) -> SymbolMapping:
        mappings = self.resolve_many(source=source, source_symbols=[source_symbol])
        try:
            return mappings[source_symbol]
        except KeyError as exc:
            raise LookupError(
                f"symbol_map missing for source={source!r}, source_symbol={source_symbol!r}"
            ) from exc

    def resolve_many(
        self,
        *,
        source: str,
        source_symbols: list[str],
    ) -> dict[str, SymbolMapping]:
        symbols = sorted({str(symbol).strip() for symbol in source_symbols if str(symbol).strip()})
        if not symbols:
            return {}

        rows = self.conn.execute(
            text(
                """
                SELECT
                    sm.source,
                    sm.source_symbol,
                    sm.instrument_id,
                    i.symbol,
                    i.asset,
                    i.exchange
                FROM meta.symbol_map sm
                JOIN meta.instruments i
                  ON i.instrument_id = sm.instrument_id
                WHERE sm.source = :source
                  AND sm.source_symbol = ANY(:source_symbols)
                """
            ),
            {"source": source, "source_symbols": symbols},
        ).mappings()

        result = {
            str(row["source_symbol"]): SymbolMapping(
                instrument_id=int(row["instrument_id"]),
                source=str(row["source"]),
                source_symbol=str(row["source_symbol"]),
                symbol=str(row["symbol"]),
                asset=str(row["asset"]),
                exchange=str(row["exchange"]),
            )
            for row in rows
        }
        missing = [symbol for symbol in symbols if symbol not in result]
        if missing:
            raise LookupError(
                f"symbol_map missing {len(missing)} symbols for source={source!r}: {missing[:20]}"
            )
        return result

