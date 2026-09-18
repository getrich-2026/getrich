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

from collections.abc import Callable
from typing import Any, Protocol, TypeVar

import pandas as pd

from gr_data.common.retry import PermanentError
from gr_data.common.ricequant_specs import BudgetDeferredError


T = TypeVar("T")


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
        *,
        fields: list[str] | None = None,
        expect_df: bool | None = None,
    ) -> pd.DataFrame: ...

    def get_quota(self) -> dict[str, Any]: ...

    def index_components(self, code: str, *, date: str) -> tuple[list[str], object] | None: ...

    def index_weights(self, code: str, *, date: str) -> pd.Series | None: ...


class RqdatacClient:
    """真实 rqdatac SDK 封装。延迟 init。"""

    def __init__(
        self,
        license_key: str | None = None,
        username: str | None = None,
        password: str | None = None,
        market: str = "cn",
        *,
        connect_timeout: float = 5,
        timeout: float = 60,
        enable_bjse: bool | None = None,
    ) -> None:
        self._license = license_key
        self._username = username
        self._password = password
        self.market = market
        self._rq: Any = None
        self._connect_timeout = connect_timeout
        self._timeout = timeout
        self._enable_bjse = enable_bjse

    @staticmethod
    def _call(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """按安装 SDK 的 rqerrno 分类，并避免异常文本泄漏认证信息。"""
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            code = getattr(exc, "rqerrno", None)
            if code == 5:
                raise BudgetDeferredError("米筐额度耗尽，保留分片等待恢复") from None
            if code in {2, 4, 6, 7, 400} or isinstance(exc, (ValueError, ImportError)):
                raise PermanentError("米筐认证、权限或参数无效，请核对所选模块与契约") from None
            if isinstance(exc, (TimeoutError, ConnectionError, OSError)) or code in {-1, -2}:
                raise ConnectionError("米筐暂态网络或服务故障") from None
            raise PermanentError("米筐出现未分类 SDK 异常，停止此任务以核对契约") from None

    def _sdk(self) -> Any:
        if self._rq is None:
            try:
                import rqdatac  # type: ignore
            except ImportError as e:  # pragma: no cover
                raise PermanentError("未安装 rqdatac SDK。") from e
            extra = {} if self._enable_bjse is None else {"enable_bjse": self._enable_bjse}
            if self._license:
                self._call(
                    rqdatac.init,
                    "license",
                    self._license,
                    connect_timeout=self._connect_timeout,
                    timeout=self._timeout,
                    **extra,
                )
            elif self._username and self._password:
                self._call(
                    rqdatac.init,
                    self._username,
                    self._password,
                    connect_timeout=self._connect_timeout,
                    timeout=self._timeout,
                    **extra,
                )
            else:
                # 不退化成无凭证的 rqdatac.init()：那样既不报错也不提示，
                # 表现成「配了 key 但取数失败」，极难定位。曾因 config.yaml 写
                # license_env: RQ_LICENSE 而环境变量叫 RICEQUANT_API_KEY，
                # 名字对不上就静默走到这一支（见 DECISIONS.md D-002）。
                raise PermanentError(
                    "缺少米筐凭证：请设置环境变量 RICEQUANT_API_KEY，"
                    "并确认 config.yaml 的 providers.ricequant.license_env 指向同一个变量名"
                    "（或改用 username_env / password_env）。"
                )
            self._rq = rqdatac
        return self._rq

    def all_instruments(self, type: str, market: str = "cn") -> pd.DataFrame:
        return self._sdk().all_instruments(type=type, market=market)

    def get_trading_dates(self, start_date: str, end_date: str, market: str = "cn") -> list[Any]:
        return list(self._call(self._sdk().get_trading_dates, start_date, end_date, market=market))

    def get_price(
        self,
        symbols: list[str],
        start_date: str,
        end_date: str,
        frequency: str = "1d",
        adjust_type: str = "none",
        market: str = "cn",
        *,
        fields: list[str] | None = None,
        expect_df: bool | None = None,
    ) -> pd.DataFrame:
        extra: dict[str, Any] = {}
        if fields is not None:
            extra["fields"] = fields
        if expect_df is not None:
            extra["expect_df"] = expect_df
        return self._call(
            self._sdk().get_price,
            symbols,
            start_date=start_date,
            end_date=end_date,
            frequency=frequency,
            adjust_type=adjust_type,
            market=market,
            **extra,
        )

    def get_quota(self) -> dict[str, Any]:
        """返回账户额度；bytes_limit=0 表示不受限，不代表无剩余额度。"""
        return self._call(self._sdk().user.get_quota)

    def index_components(self, code: str, *, date: str) -> tuple[list[str], object] | None:
        """查询指定业务日的完整成员及原始入库时间，不降级为无时间列表。"""
        return self._call(
            self._sdk().index_components, code, date=date, market=self.market, return_create_tm=True
        )

    def index_weights(self, code: str, *, date: str) -> pd.Series | None:
        """仅使用已核对的单日签名，返回原生权重尺度。"""
        return self._call(self._sdk().index_weights, code, date=date)

    def risk_piece(
        self, piece: str, day: str, codes: list[str], *, model: str, industry_mapping: str
    ) -> pd.DataFrame | None:
        """标准风险五件套的已核对签名；风险期限固定 daily，不猜测源单位。"""
        parameters = {"model": model, "industry_mapping": industry_mapping}
        sdk = self._sdk()
        if piece == "covariance":
            return self._call(sdk.get_factor_covariance, day, horizon="daily", **parameters)
        if piece == "factor_return":
            return self._call(
                sdk.get_factor_return,
                day,
                day,
                factors=None,
                universe="whole_market",
                method="implicit",
                market="cn",
                **parameters,
            )
        if piece == "exposure":
            return self._call(
                sdk.get_factor_exposure, codes, day, day, factors=None, market="cn", **parameters
            )
        if piece == "specific_return":
            return self._call(sdk.get_specific_return, codes, day, day, **parameters)
        if piece == "specific_risk":
            return self._call(sdk.get_specific_risk, codes, day, day, horizon="daily", **parameters)
        raise PermanentError("未知米筐风险接口")
