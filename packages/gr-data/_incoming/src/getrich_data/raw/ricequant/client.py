"""米筐 rqdatac 客户端封装。

定义 ``RicequantClient`` 协议与真实 SDK 实现 ``RqdatacClient``。

真实 SDK 用法（来自现有代码核对）::

    import rqdatac
    rqdatac.init("license", license_key)  # 或 rqdatac.init(user, password)
    rqdatac.all_instruments(type="CS", market="cn", date=None) -> DataFrame
    rqdatac.get_trading_dates(start_date, end_date, market="cn") -> list[date]
    rqdatac.get_price(symbols, start_date, end_date, frequency="1d",
                      adjust_type="none", market="cn") -> DataFrame
"""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd

# 米筐 asset -> all_instruments type
RQ_TYPE_MAP = {
    "stock": "CS",
    "index": "Index",
    "etf": "ETF",
    "future": "Future",
    "option": "Option",
}


class RicequantClient(Protocol):
    def all_instruments(self, type: str, market: str = "cn") -> pd.DataFrame: ...

    def get_trading_dates(
        self, start_date: str, end_date: str, market: str = "cn"
    ) -> list[Any]: ...

    def get_price(
        self,
        symbols: list[str],
        start_date: str,
        end_date: str,
        frequency: str = "1d",
        adjust_type: str = "none",
        market: str = "cn",
    ) -> pd.DataFrame: ...


class RqdatacClient:
    """真实 rqdatac SDK 封装。延迟 init。"""

    def __init__(
        self,
        license_key: str | None = None,
        username: str | None = None,
        password: str | None = None,
        market: str = "cn",
    ):
        self._license = license_key
        self._username = username
        self._password = password
        self.market = market
        self._rq: Any = None

    def _sdk(self) -> Any:
        if self._rq is None:
            try:
                import rqdatac  # type: ignore
            except ImportError as e:  # pragma: no cover
                raise RuntimeError("未安装 rqdatac SDK。") from e
            if self._license:
                rqdatac.init("license", self._license)
            elif self._username and self._password:
                rqdatac.init(self._username, self._password)
            else:
                rqdatac.init()
            self._rq = rqdatac
        return self._rq

    def all_instruments(self, type: str, market: str = "cn") -> pd.DataFrame:
        return self._sdk().all_instruments(type=type, market=market)

    def get_trading_dates(
        self, start_date: str, end_date: str, market: str = "cn"
    ) -> list[Any]:
        return list(self._sdk().get_trading_dates(start_date, end_date, market=market))

    def get_price(
        self,
        symbols: list[str],
        start_date: str,
        end_date: str,
        frequency: str = "1d",
        adjust_type: str = "none",
        market: str = "cn",
    ) -> pd.DataFrame:
        return self._sdk().get_price(
            symbols,
            start_date=start_date,
            end_date=end_date,
            frequency=frequency,
            adjust_type=adjust_type,
            market=market,
        )
