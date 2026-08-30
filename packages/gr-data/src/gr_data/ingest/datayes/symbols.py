"""通联证券编码的归一化。

通联的 `secID` 形如 ``000002.XSHE``：交易代码 + **canonical 交易所码**。
而 `meta.instruments.symbol` 存的是 tushare 形态的 ``000002.SZ``。
两者不是同一串，直接拿 `secID` 查 `meta.symbol_map` 会**一条都命中不了**
（而且不报错，只会表现为「这批数据全是未登记标的」）。

对齐方式按 AGENTS.md §3.4：跨源对齐一律经 `meta.symbol_map`。
`DatayesSymbolMapImporter` 先把 ``(source='datayes', source_symbol='000002.XSHE')``
写进映射表，之后所有 datayes importer 统一走现成的
`resolve_by_symbol_map(conn, "datayes")`，不在各处做临时的后缀互转。

后缀集合是**待实测确认项**（U21）：下面这张表只覆盖已在文档与样本里见过的三个
市场。未知后缀原样大写返回、**不静默改写**（照 `ingest/tushare/symbols.py` 的做法），
`@live_sdk` 里有一条探针用例会枚举真实返回的后缀，出现新后缀就失败 ——
那正是我们想要的信号。
"""

from __future__ import annotations


#: 通联 exchangeCD → 本仓 canonical exchange。通联用的本来就是 canonical 码，
#: 所以这张表目前是恒等映射；留着它是为了让「哪些后缀被认可」有一处可查。
DATAYES_SUFFIX_TO_EXCHANGE: dict[str, str] = {
    "XSHG": "XSHG",  # 上交所
    "XSHE": "XSHE",  # 深交所
    "XBSE": "XBSE",  # 北交所
}

#: canonical exchange → tushare 后缀，用于把 secID 折算成 meta.instruments.symbol。
#: 只在首次建立 symbol_map 时用一次，之后一律走 symbol_map。
EXCHANGE_TO_TUSHARE_SUFFIX: dict[str, str] = {
    "XSHG": "SH",
    "XSHE": "SZ",
    "XBSE": "BJ",
}


def split_sec_id(sec_id: str) -> tuple[str, str]:
    """``000002.XSHE`` → ``("000002", "XSHE")``。

    无后缀返回 ``(原串, "UNKNOWN")``；未知后缀原样大写返回，不猜测、不改写。
    """
    s = str(sec_id).strip()
    if "." not in s:
        return s, "UNKNOWN"
    ticker, _, suffix = s.rpartition(".")
    suffix = suffix.upper()
    return ticker, DATAYES_SUFFIX_TO_EXCHANGE.get(suffix, suffix)


def to_tushare_symbol(sec_id: str) -> str | None:
    """``000002.XSHE`` → ``000002.SZ``（= `meta.instruments.symbol` 的形态）。

    交易所无法识别时返回 None —— 由调用方决定是告警跳过还是中断，
    这里不猜一个后缀凑数。
    """
    ticker, exchange = split_sec_id(sec_id)
    suffix = EXCHANGE_TO_TUSHARE_SUFFIX.get(exchange)
    if suffix is None or not ticker:
        return None
    return f"{ticker}.{suffix}"
