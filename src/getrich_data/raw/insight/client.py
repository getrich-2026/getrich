"""华泰 INSIGHT 客户端封装。

定义 ``InsightClient`` 协议与真实 SDK 实现 ``InsightApiClient``。

真实 SDK 用法（来自现有代码核对）::

    from insight_python.com.insight.query import get_all_basic_info, get_kline, get_trading_days
    from insight_python.com.insight.common import login
    from insight_python.com.insight.market_service import market_service
    login(market_service(), user, password)
    get_all_basic_info(security_type=..., exchange=[...]) -> DataFrame
    get_trading_days(exchange=..., trading_day=[start_ts, end_ts]) -> DataFrame/tuple
    get_kline(htsc_code=..., time=[start_ts, end_ts], frequency="daily", fq="none") -> DataFrame
"""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd


class InsightClient(Protocol):
    def get_all_basic_info(self, security_type: str, exchange: list[str]) -> pd.DataFrame: ...

    def get_trading_days(self, exchange: str, trading_day: list[int]) -> pd.DataFrame: ...

    def get_kline(
        self, htsc_code: list[str], time: list[int], frequency: str, fq: str
    ) -> pd.DataFrame: ...


class InsightApiClient:
    """真实 INSIGHT SDK 封装。延迟 login。"""

    def __init__(self, username: str, password: str):
        self._username = username
        self._password = password
        self._q: Any = None

    def _ensure_login(self) -> Any:
        if self._q is None:
            try:
                from insight_python.com.insight import query as q  # type: ignore
                from insight_python.com.insight.common import login  # type: ignore
                from insight_python.com.insight.market_service import market_service  # type: ignore
            except ImportError as e:  # pragma: no cover
                raise RuntimeError("未安装 insight_python SDK。") from e
            login(market_service(), self._username, self._password)
            self._q = q
        return self._q

    def get_all_basic_info(self, security_type: str, exchange: list[str]) -> pd.DataFrame:
        return self._ensure_login().get_all_basic_info(
            security_type=security_type, exchange=exchange
        )

    def get_trading_days(self, exchange: str, trading_day: list[int]) -> pd.DataFrame:
        return self._ensure_login().get_trading_days(
            exchange=exchange, trading_day=trading_day
        )

    def get_kline(
        self, htsc_code: list[str], time: list[int], frequency: str, fq: str
    ) -> pd.DataFrame:
        return self._ensure_login().get_kline(
            htsc_code=htsc_code, time=time, frequency=frequency, fq=fq
        )
