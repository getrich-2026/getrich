# Author: QiuZiHua
# Date: 2025-01-29
# Description: RiceQuant Data API - Refactored for Polars & Project Standards

import polars as pl
from lntools.utils import Logger

from getrich.config.settings import settings

# Initialize Logger
log = Logger(module_name="RQDataAPI")

# Attempt to import rqdatac based on settings
HAS_RQDATAC = False
if settings.ricequant.enabled:
    try:
        import rqdatac as rq

        HAS_RQDATAC = True  # type: ignore
    except ImportError:
        log.warning("Failed to import rqdatac, please check installation")
else:
    log.info("RiceQuant is disabled in settings")


class RQDataAPI:
    """RiceQuant 数据源实现类"""

    def __init__(self) -> None:
        self.is_initialized = False

    def login(self) -> None:
        """登录RiceQuant数据源"""
        if not HAS_RQDATAC:
            log.error("rqdatac SDK not installed or disabled, cannot login")
            return

        api_key = settings.ricequant.api_key
        if not api_key:
            log.error("RiceQuant API key not configured, please check settings or .env")
            return

        try:
            rq.init("license", api_key)  # pyright: ignore[reportPossiblyUnboundVariable]
            self.is_initialized = True
            log.info("RiceQuant connection initialized successfully")
        except Exception as e:
            log.error(f"RiceQuant login exception: {e}")
            raise RuntimeError(f"RiceQuant login failed: {e}") from e

    def get_all_instruments(
        self, inst_type: str = "CS", date: str | None = None, market: str = "cn"
    ) -> pl.DataFrame:
        """获取所有合约基础信息

        Args:
            inst_type: 合约类型，如 CS, ETF, Future, Option 等
            date: 查询日期，格式 'YYYY-MM-DD'，None 表示最新
            market: 市场代码，默认 'cn'

        Returns:
            pl.DataFrame: 合约信息
        """
        if not HAS_RQDATAC:
            log.error("rqdatac not available")
            return pl.DataFrame()

        try:
            import pandas as pd

            df_pandas: pd.DataFrame = rq.all_instruments(type=inst_type, date=date, market=market)  # pyright: ignore[reportPossiblyUnboundVariable]

            if df_pandas.empty:
                log.warning(f"No instruments found for type {inst_type}")
                return pl.DataFrame()

            df = pl.from_pandas(df_pandas)
            log.info(f"Fetched {len(df)} instruments for type {inst_type}")
            return df
        except Exception as e:
            log.error(f"get_all_instruments error: {e}")
            return pl.DataFrame()

    def get_trade_day_list(self, start_date: str, end_date: str) -> pl.DataFrame:
        """从RiceQuant获取交易日列表"""
        if not HAS_RQDATAC:
            return pl.DataFrame()

        try:
            trading_days = rq.get_trading_dates(start_date, end_date, market="cn")  # pyright: ignore[reportPossiblyUnboundVariable]

            if len(trading_days) == 0:
                log.warning("RiceQuant get_trading_dates returned empty data")
                return pl.DataFrame()

            # Convert to DataFrame
            df = pl.DataFrame(
                {
                    "交易日": [str(d) for d in trading_days],
                    "数据源": ["RiceQuant"] * len(trading_days),
                }
            )

            return df
        except Exception as e:
            log.error(f"get_trade_day_list error: {e}")
            return pl.DataFrame()
