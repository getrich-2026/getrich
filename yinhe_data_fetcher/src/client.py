"""AmazingData 客户端封装 - 登录 + 懒加载 BaseData / MarketData / DownloadInfoData."""

from __future__ import annotations

from threading import Lock
from typing import Any

from .config import AmazingDataCfg
from .logger import get_logger

_LOGIN_LOCK = Lock()
_LOGGED_IN = False


class AmazingDataClient:
    """对 AmazingData SDK 的轻量封装.

    - 登录只做一次 (模块级锁)
    - 暴露常用对象: base_data, market_data, download_info_data
    - calendar 在第一次访问时拉取并缓存 (多个 fetcher 共用)
    """

    def __init__(self, cfg: AmazingDataCfg):
        self.cfg = cfg
        self._ad: Any | None = None
        self._base_data: Any | None = None
        self._market_data: Any | None = None
        self._download_info_data: Any | None = None
        self._calendar: list[int] | None = None
        self._log = get_logger("client")

    # ------------------------------------------------------------------
    # 登录
    # ------------------------------------------------------------------
    def login(self) -> None:
        global _LOGGED_IN
        with _LOGIN_LOCK:
            if _LOGGED_IN and self._ad is not None:
                return
            import AmazingData as ad  # type: ignore

            self._log.info(
                "login AmazingData host=%s port=%s user=%s",
                self.cfg.host,
                self.cfg.port,
                self.cfg.username,
            )
            # SDK 文档里 host=ip, port=端口
            ad.login(
                username=self.cfg.username,
                password=self.cfg.password,
                host=self.cfg.host,
                port=self.cfg.port,
            )
            self._ad = ad
            _LOGGED_IN = True

    @property
    def ad(self) -> Any:
        if self._ad is None:
            self.login()
        assert self._ad is not None
        return self._ad

    # ------------------------------------------------------------------
    # 常用对象
    # ------------------------------------------------------------------
    @property
    def base_data(self) -> Any:
        if self._base_data is None:
            self._base_data = self.ad.BaseData()
        return self._base_data

    def market_data(self, calendar: list[int] | None = None) -> Any:
        """MarketData 需要 calendar 作为入参, 每次可以传入新的 calendar 构造."""
        cal = calendar if calendar is not None else self.calendar
        if self._market_data is None:
            self._market_data = self.ad.MarketData(cal)
        return self._market_data

    def download_info_data(self, local_path: str) -> Any:
        if self._download_info_data is None:
            self._download_info_data = self.ad.DownloadInfoData(local_path)
        return self._download_info_data

    # ------------------------------------------------------------------
    # calendar 缓存 - 被绝大多数 fetcher 依赖
    # ------------------------------------------------------------------
    @property
    def calendar(self) -> list[int]:
        if self._calendar is None:
            self._log.info("fetch SH trading calendar")
            cal = self.base_data.get_calendar(market="SH")
            # SDK 返回可能是 list[int] / np.ndarray / pd.Series
            self._calendar = [int(x) for x in list(cal)]
        return self._calendar
