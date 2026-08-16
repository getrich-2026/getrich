"""银河 AmazingData 客户端封装。

定义 ``YinheClient`` 协议（raw fetcher 依赖的最小接口），与真实 SDK 实现
``AmazingDataClient``。测试时可注入实现了同协议的 Fake，无需真实 SDK/网络。

真实 SDK 用法（来自现有代码核对）::

    import AmazingData as ad
    ad.login(username=..., password=..., host=..., port=...)
    ad.BaseData().get_calendar(market="SH")            -> list[int8]
    ad.BaseData().get_code_list(security_type=...)     -> list[str]
    ad.BaseData().get_backward_factor(codes, local_path=..., is_local=False) -> DataFrame
    ad.MarketData(calendar).query_kline(codes, begin_date, end_date, period=<int>) -> dict[str, DataFrame]
    ad.constant.Period.<name>.value                    -> int
"""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd

from getrich_data.common.logging import get_logger

log = get_logger("raw.yinhe.client")


class YinheClient(Protocol):
    """raw/yinhe fetcher 依赖的最小接口。"""

    def get_calendar(self, market: str) -> list[int]: ...

    def get_code_list(self, security_type: str) -> list[str]: ...

    def get_backward_factor(self, codes: list[str]) -> pd.DataFrame: ...

    def query_kline(
        self, codes: list[str], begin_date: int, end_date: int, period: str
    ) -> dict[str, pd.DataFrame]: ...


class AmazingDataClient:
    """真实 AmazingData SDK 封装。延迟导入 SDK，未安装时报清晰错误。"""

    def __init__(self, username: str, password: str, host: str, port: int):
        self._username = username
        self._password = password
        self._host = host
        self._port = port
        self._ad: Any = None
        self._base: Any = None
        self._calendar: list[int] | None = None

    def _sdk(self) -> Any:
        if self._ad is None:
            try:
                import AmazingData as ad  # type: ignore
            except ImportError as e:  # pragma: no cover - 依赖真实环境
                raise RuntimeError(
                    "未安装 AmazingData SDK。请安装银河量化 SDK 后重试。"
                ) from e
            ad.login(
                username=self._username,
                password=self._password,
                host=self._host,
                port=self._port,
            )
            self._ad = ad
        return self._ad

    def _base_data(self) -> Any:
        if self._base is None:
            self._base = self._sdk().BaseData()
        return self._base

    def get_calendar(self, market: str) -> list[int]:
        cal = list(self._base_data().get_calendar(market=market))
        self._calendar = [int(x) for x in cal]
        return self._calendar

    def get_code_list(self, security_type: str) -> list[str]:
        return [str(c) for c in self._base_data().get_code_list(security_type=security_type)]

    def get_backward_factor(self, codes: list[str]) -> pd.DataFrame:
        return self._base_data().get_backward_factor(codes, is_local=False)

    def query_kline(
        self, codes: list[str], begin_date: int, end_date: int, period: str
    ) -> dict[str, pd.DataFrame]:
        ad = self._sdk()
        period_value = getattr(ad.constant.Period, period).value
        if self._calendar is None:
            self.get_calendar("SH")
        market = ad.MarketData(self._calendar)
        return market.query_kline(
            codes, begin_date=begin_date, end_date=end_date, period=period_value
        )
