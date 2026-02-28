"""
Author: <QiuZiHua>
Date: 2026-01-29
Description: 同花顺 iFinD 数据接口
"""

from __future__ import annotations

import pandas as pd
import polars as pl
from lntools.utils import Logger


# Initialize Logger
log = Logger(module_name="IFindAPI")

try:
    from iFinDPy import THS_DR, THS_Date_Query, THS_iFinDLogin  # type: ignore
except ImportError:
    THS_DR = None  # type: ignore[assignment]
    THS_Date_Query = None  # type: ignore[assignment]
    THS_iFinDLogin = None  # type: ignore[assignment]
    log.warning("Failed to import iFinDPy, please check installation")
    has_ifind = False
else:
    has_ifind = True


class THDataAPI:
    """同花顺数据源实现类"""

    def login(self) -> None:
        """登录同花顺数据源"""
        if not has_ifind or THS_iFinDLogin is None:
            log.error("iFinDPy not installed, cannot login")
            return

        # TODO: Move to settings if needed
        thslogin = THS_iFinDLogin("xyzhsm003", "zihuaXY2025")
        if thslogin != 0:
            log.error("iFinDPy login failed")
        else:
            log.info("iFinDPy login successful")

    def get_trade_day_list(self, start_date: str, end_date: str) -> pl.DataFrame:
        """从同花顺获取交易日列表"""
        if not has_ifind or THS_Date_Query is None:
            return pl.DataFrame()

        try:
            data = THS_Date_Query(
                "212001",
                "mode:1,dateType:0,period:D,dateFormat:0",
                start_date,
                end_date,
                "format:dict",
            )
            # THS returns custom object, assuming .data is list of dicts
            if hasattr(data, "data"):
                pdf = pd.DataFrame(data.data)
                df = pl.from_pandas(pdf)
                df = df.rename({"time": "交易日"})
                df = df.with_columns(pl.lit("同花顺").alias("数据源"))
                return df
            return pl.DataFrame()
        except Exception as e:
            log.error(f"THS get_trade_day_list error: {e}")
            return pl.DataFrame()

    def get_option_trading_contract(
        self, date: str | None = None, undcode: str | None = None
    ) -> pl.DataFrame | None:
        if date is None or not has_ifind or THS_DR is None:
            return None

        try:
            data = THS_DR(
                "p02653",
                f"sdate={date};edate={date};bdid={undcode};hyzt=0",
                "p02653_f001:Y,p02653_f002:Y,p02653_f008:Y,"
                "p02653_f011:Y,p02653_f014:Y,p02653_f015:Y,"
                "p02653_f016:Y,p02653_f005:Y",
                "format:dataframe",
            )

            if hasattr(data, "data") and isinstance(data.data, pd.DataFrame):
                df = pl.from_pandas(data.data)

                rename_map = {
                    "p02653_f001": "合约代码",
                    "p02653_f002": "合约名称",
                    "p02653_f008": "标的代码",
                    "p02653_f011": "认购认沽",
                    "p02653_f014": "合约乘数",
                    "p02653_f015": "行权价格",
                    "p02653_f016": "上市日期",
                    "p02653_f005": "到期日",
                }
                df = df.rename({k: v for k, v in rename_map.items() if k in df.columns})
                df = df.with_columns(pl.lit("同花顺").alias("数据源"))
                return df

            return None
        except Exception as e:
            log.error(f"THS get_option_trading_contract error: {e}")
            return None

    def get_stock_market_quote(self, date: str | None = None) -> pl.DataFrame | None:
        log.warning("Getting stock data from iFinDPy is not implemented yet")
        return None

    def get_com_futures_market_quote(
        self, date: str | None = None, futcode: str | None = None
    ) -> pl.DataFrame | None:
        if date is None or futcode is None or not has_ifind or THS_DR is None:
            return None

        try:
            exchangecode = {
                "212020003": "郑商所",
                "212020004": "大商所",
                "212020008": "上期所",
                "212020019": "广期所",
            }
            frames = []
            for code in exchangecode:
                data = THS_DR(
                    "p03258",
                    f"sdate={date};edate={date};jysid={code};qhpzid={futcode};qhhyid={futcode}",
                    "p03258_f001:Y,p03258_f002:Y,p03258_f003:Y,"
                    "p03258_f004:Y,p03258_f005:Y,p03258_f006:Y,"
                    "p03258_f007:Y,p03258_f008:Y,p03258_f009:Y,"
                    "p03258_f010:Y,p03258_f011:Y,p03258_f012:Y,"
                    "p03258_f013:Y,p03258_f014:Y,p03258_f015:Y,"
                    "p03258_f016:Y,p03258_f017:Y",
                    "format:dataframe",
                )

                if data.errorcode != 0:
                    log.error(f"THS error code: {data.errorcode} msg: {data.errmsg}")
                    return None

                if hasattr(data, "data") and isinstance(data.data, pd.DataFrame):
                    df = pl.from_pandas(data.data)

                    rename_map = {
                        "p03258_f001": "合约代码",
                        "p03258_f002": "合约名称",
                        "p03258_f003": "交易日期",
                        "p03258_f004": "前结算价",
                        "p03258_f005": "开盘价",
                        "p03258_f006": "最高价",
                        "p03258_f007": "最低价",
                        "p03258_f008": "收盘价",
                        "p03258_f009": "平均价",
                        "p03258_f010": "涨跌(收-结)",
                        "p03258_f011": "涨跌(结-结)",
                        "p03258_f012": "涨跌幅",
                        "p03258_f013": "持仓量",
                        "p03258_f014": "日增仓",
                        "p03258_f015": "成交量",
                        "p03258_f016": "成交金额(万元)",
                        "p03258_f017": "成交金额变化率(%)",
                    }
                    df = df.rename({k: v for k, v in rename_map.items() if k in df.columns})
                    frames.append(df)

            if frames:
                df_pool = pl.concat(frames)
                df_pool = df_pool.with_columns(pl.lit("同花顺").alias("数据源"))
                return df_pool
            return pl.DataFrame()
        except Exception as e:
            log.error(f"THS get_com_futures_market_quote error: {e}")
            return None

    def get_futures_market_quote(self, date: str | None = None) -> pl.DataFrame | None:
        if date is None or not has_ifind or THS_DR is None:
            return None

        try:
            data = THS_DR(
                "p00755",
                f"sclx=中金所股指期货;date={date}",
                "p00755_f001:Y,"
                "p00755_f002:Y,p00755_f003:Y,"
                "p00755_f004:Y,p00755_f005:Y,"
                "p00755_f006:Y,p00755_f007:Y,"
                "p00755_f008:Y,p00755_f009:Y,"
                "p00755_f014:Y,p00755_f017:Y,"
                "p00755_f020:Y,p00755_f023:Y,"
                "format:dataframe",
            )

            if data.errorcode != 0:
                log.error(f"THS error code: {data.errorcode} msg: {data.errmsg}")
                return None

            if hasattr(data, "data") and isinstance(data.data, pd.DataFrame):
                df = pl.from_pandas(data.data)

                rename_map = {
                    "p00755_f001": "合约代码",
                    "p00755_f002": "合约名称",
                    "p00755_f003": "交易日期",
                    "p00755_f004": "前结算价",
                    "p00755_f005": "前收盘价",
                    "p00755_f006": "开盘价",
                    "p00755_f007": "最高价",
                    "p00755_f008": "最低价",
                    "p00755_f009": "收盘价",
                    "p00755_f014": "结算价",
                    "p00755_f017": "持仓量",
                    "p00755_f020": "成交量",
                    "p00755_f023": "成交金额(万元)",
                }
                df = df.rename({k: v for k, v in rename_map.items() if k in df.columns})
                df = df.with_columns(pl.lit("同花顺").alias("数据源"))
                return df
            return None
        except Exception as e:
            log.error(f"THS get_futures_market_quote error: {e}")
            return None

    def get_option_market_quote(
        self,
        exchange: str | None = None,
        date: str | None = None,
        undcode: str | None = None,
        undname: str | None = None,
    ) -> pl.DataFrame | None:
        if (
            date is None
            or exchange is None
            or undname is None
            or undcode is None
            or not has_ifind
            or THS_DR is None
        ):
            return None

        try:
            df_res = THS_DR(
                "p02834",
                f"sdate={date};edate={date};jys={exchange};bdpz={undname};bdhy={undcode};qqhy=全部",
                "p02834_f028:Y,p02834_f027:Y,p02834_f001:Y,p02834_f002:Y,p02834_f003:Y,"
                "p02834_f004:Y,p02834_f005:Y,p02834_f006:Y,p02834_f007:Y,p02834_f008:Y,p02834_f012:Y,"
                "p02834_f013:Y,p02834_f014:Y,p02834_f015:Y,p02834_f017:Y,p02834_f024:Y,p02834_f026:Y,p02834_f025:Y",
                "format:dataframe",
            )

            if df_res.errorcode != 0:
                log.error(f"THS error code: {df_res.errorcode} msg: {df_res.errmsg}")
                return None

            if hasattr(df_res, "data") and isinstance(df_res.data, pd.DataFrame):
                df = pl.from_pandas(df_res.data)

                rename_map = {
                    "p02834_f028": "合约代码",
                    "p02834_f027": "合约名称",
                    "p02834_f001": "交易日期",
                    "p02834_f002": "前结算价",
                    "p02834_f003": "开盘价",
                    "p02834_f004": "最高价",
                    "p02834_f005": "最低价",
                    "p02834_f006": "收盘价",
                    "p02834_f007": "结算价",
                    "p02834_f008": "前收盘价",
                    "p02834_f012": "成交量",
                    "p02834_f013": "成交额(万元)",
                    "p02834_f014": "持仓量",
                    "p02834_f015": "持仓量变化",
                    "p02834_f017": "行权价",
                    "p02834_f024": "到期剩余天数",
                    "p02834_f026": "到期剩余交易日",
                    "p02834_f025": "到期日",
                }
                df = df.rename({k: v for k, v in rename_map.items() if k in df.columns})
                df = df.with_columns(pl.lit("同花顺").alias("数据源"))
                return df

            return None
        except Exception as e:
            log.error(f"THS get_option_market_quote error: {e}")
            return None

    def get_etf_market_quote(
        self, start_date: str | None = None, end_date: str | None = None, etfcode: str | None = None
    ) -> pl.DataFrame | None:
        log.warning("Getting ETF data from iFinDPy is not implemented yet")
        return None

    def get_fund_daily_info(self) -> pl.DataFrame | None:
        log.warning("Getting fund data from iFinDPy is not implemented yet")
        return None

    def get_rate_market_quote(self) -> pl.DataFrame | None:
        log.warning("Getting repo rate data from iFinDPy is not implemented yet")
        return None

    def get_cbond_info(self, date: str | None = None) -> pl.DataFrame | None:
        log.warning("Getting convertible bond info from iFinDPy is not supported yet")
        return None

    def get_cbond_market_quote(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        cbondcode: str | None = None,
    ) -> pl.DataFrame | None:
        log.warning("Getting convertible bond quotes from iFinDPy is not supported yet")
        return None

    def get_fund_market_quote(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        fundcode: str | None = None,
    ) -> pl.DataFrame | None:
        log.warning("Getting fund NAV data from iFinDPy is not supported yet")
        return None

    def get_index_daily_info(self) -> pl.DataFrame | None:
        log.warning("Getting index info from iFinDPy is not supported yet")
        return None

    def get_index_market_quote(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        indexcode: str | None = None,
    ) -> pl.DataFrame | None:
        log.warning("Getting index quotes from iFinDPy is not supported yet")
        return None

    def get_option_basic_info(self, undcode: str | None = None) -> pl.DataFrame | None:
        log.warning("Getting option contract info from iFinDPy is not supported yet")
        return None
