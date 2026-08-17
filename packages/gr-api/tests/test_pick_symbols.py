"""``services/pick_symbols`` 的解析与两套交易所码映射。

这个模块看着简单，但它是「接口契约的 SSE」与「数据层 canonical 的 XSHG」
之间唯一的翻译层 —— 映射写反不会报错，只会让 instrument_id 整批为 NULL、
交易日历一条都查不到。
"""

from __future__ import annotations

import pytest
from gr_api.services import pick_symbols


@pytest.mark.parametrize(
    ("raw", "symbol", "exchange"),
    [
        ("600000.SH", "600000", "SSE"),
        ("000001.SZ", "000001", "SZSE"),
        ("830799.BJ", "830799", "BSE"),
        ("  600000.sh  ", "600000", "SSE"),  # 前后空白与小写后缀都接受
    ],
)
def test_parse_symbol_accepts_suffixed_codes(raw: str, symbol: str, exchange: str) -> None:
    parsed = pick_symbols.parse_symbol(raw)

    assert parsed.symbol == symbol
    assert parsed.exchange == exchange
    assert parsed.symbol_full == f"{symbol}.{pick_symbols.EXCHANGE_TO_SUFFIX[exchange]}"
    # P0 一律标 stock，品种代码等于证券代码（无换月概念）。
    assert parsed.asset_class == "stock"
    assert parsed.product_code == symbol


@pytest.mark.parametrize(
    "raw",
    ["600000", "sh600000", "600000.SS", "60000.SH", "6000000.SH", "", "600000.SH.SH"],
)
def test_parse_symbol_rejects_everything_else(raw: str) -> None:
    """强制后缀是整个简化方案的核心：不做任何推断和兼容。"""
    with pytest.raises(ValueError, match="invalid symbol"):
        pick_symbols.parse_symbol(raw)


def test_leading_zero_symbol_survives_parsing() -> None:
    assert pick_symbols.parse_symbol("000001.SZ").symbol == "000001"


def test_to_symbol_full_round_trips() -> None:
    for raw in ("600000.SH", "000001.SZ", "830799.BJ"):
        parsed = pick_symbols.parse_symbol(raw)
        assert pick_symbols.to_symbol_full(parsed.symbol, parsed.exchange) == raw


def test_to_symbol_full_unknown_exchange_returns_symbol() -> None:
    assert pick_symbols.to_symbol_full("IF2609", "CFFEX") == "IF2609"


def test_canonical_exchange_mapping_matches_data_layer() -> None:
    """必须与 gr_data.ingest.tushare.symbols 的 canonical 码一致。"""
    from gr_data.ingest.tushare.symbols import SUFFIX_TO_EXCHANGE as DATA_LAYER

    for suffix, contract_exchange in pick_symbols.SUFFIX_TO_EXCHANGE.items():
        assert pick_symbols.to_canonical_exchange(contract_exchange) == DATA_LAYER[suffix]


def test_canonical_exchange_passthrough_for_unknown() -> None:
    assert pick_symbols.to_canonical_exchange("SHFE") == "SHFE"


def test_calendar_exchange_is_canonical() -> None:
    """交易日历表里存的是 canonical 码，用 'SSE' 去查会一条都查不到。"""
    assert pick_symbols.CALENDAR_EXCHANGE == "XSHG"
