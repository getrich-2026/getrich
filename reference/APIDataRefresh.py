# 这个函数的功能是为了让API获得的数据重新整理
# 目前API数据来源有：1. ricequant；2. insight
# 重构后的数据存在：/getrich_data
# 重构后分为以下数据：
#    1. /getrich_data/证券信息/*tpye*;
#    2. /getrich_data/交易日历/；
#    3. /getrich_data/日线数据/*type*；
#    4. /getrich_data/分钟数据/*type*
#    5. /getrich_data/个股数据/财务指标/*type*
#    6. /getrich_data/个股数据/股票估值/*type*
# ================================================================================
# 证券信息数据结构说明
# ================================================================================

"""
================================================================================
证券信息数据字典 (Symbol Info Data Dictionary)
================================================================================

以下字段说明适用于证券信息表，包含股票、期货、期权、债券、指数、基金等各类资产的基础信息。

【字段说明表】

+---------------+--------+----------------------------------------------------------------------------------+
| 字段          | 类型   | 说明                                                                             |
+===============+========+==================================================================================+
| symbol        | str    | 代码                                                                             |
|               |        | 代码结尾：{上交所:.SH}; {深交所:.SZ}; {北交所:.BJ}; {上期所:.SHF};               |
|               |        | {广期所:.GFE}; {大商所:.DCE}; {郑商所:.CZC}; {中金所:.CFE}; {能源所:.INE}        |
+---------------+--------+----------------------------------------------------------------------------------+
| dt            | date   | 日期，格式：yyyy-mm-dd                                                           |
+---------------+--------+----------------------------------------------------------------------------------+
| exchange      | str    | 交易所代码                                                                       |
|               |        | 上交所：SH；深交所：SZ；北交所：BJ；上期所：SHF；郑商所：CZC；                   |
|               |        | 大商所：DCE；广期所：GFE；能源所：INE；中金所：CFE                               |
+---------------+--------+----------------------------------------------------------------------------------+
| name          | str    | 证券名称                                                                         |
+---------------+--------+----------------------------------------------------------------------------------+
| type          | str    | 证券类型：stock; future; option; bond; index; fund                               |
+---------------+--------+----------------------------------------------------------------------------------+
| und_code      | str    | 标的代码；没有的等于symbol；可转债是正股代码                                     |
+---------------+--------+----------------------------------------------------------------------------------+
| und_name      | str    | 标的简称；没有的等于name；可转债是正股名称                                       |
+---------------+--------+----------------------------------------------------------------------------------+
| optiontype    | str    | 期权类型：call or put；其他为空                                                  |
+---------------+--------+----------------------------------------------------------------------------------+
| strike        | float  | 行权价；期权类才有，其他为空                                                     |
+---------------+--------+----------------------------------------------------------------------------------+
| multiplier    | float  | 合约乘数；股票、债券这些为1                                                      |
+---------------+--------+----------------------------------------------------------------------------------+
| listed_date   | date   | 上市日期                                                                         |
+---------------+--------+----------------------------------------------------------------------------------+
| delisted_date | date   | 退市日期（默认为2099-12-31）                                                     |
+---------------+--------+----------------------------------------------------------------------------------+
| source        | str    | 数据来源：ricequant; insight                                                     |
+---------------+--------+----------------------------------------------------------------------------------+
| updated_at    | date   | 数据更新时间；存在本地的parquet不需要；上传clickhouse需要                        |
+---------------+--------+----------------------------------------------------------------------------------+

================================================================================
交易日历数据字典 (Trading Calendar Data Dictionary)
================================================================================

以下字段说明适用于交易日历表。

【字段说明表】

+---------------+--------+----------------------------------------------------------------------------------+
| 字段          | 类型   | 说明                                                                             |
+===============+========+==================================================================================+
| dt            | date   | yyyy-mm-dd                                                                       |
+---------------+--------+----------------------------------------------------------------------------------+

================================================================================
日线数据字典 (Daily Bar Data Dictionary)
================================================================================

以下字段说明适用于日线数据表。

【字段说明表】

+---------------+--------+----------------------------------------------------------------------------------+
| 字段          | 类型   | 说明                                                                             |
+===============+========+==================================================================================+
| symbol        | str    | 证券代码                                                                         |
+---------------+--------+----------------------------------------------------------------------------------+
| dt            | date   | 交易日期                                                                         |
+---------------+--------+----------------------------------------------------------------------------------+
| open          | float  | 开盘价                                                                           |
+---------------+--------+----------------------------------------------------------------------------------+
| high          | float  | 最高价                                                                           |
+---------------+--------+----------------------------------------------------------------------------------+
| low           | float  | 最低价                                                                           |
+---------------+--------+----------------------------------------------------------------------------------+
| close         | float  | 收盘价                                                                           |
+---------------+--------+----------------------------------------------------------------------------------+
| volume        | float  | 成交量                                                                           |
+---------------+--------+----------------------------------------------------------------------------------+
| amount        | float  | 成交额                                                                           |
+---------------+--------+----------------------------------------------------------------------------------+
| open_interest | float  | 持仓量；除了期权期货外，其他品种为空                                             |
+---------------+--------+----------------------------------------------------------------------------------+
| settle        | float  | 结算价；除了期权期货外，其他品种为空                                             |
+---------------+--------+----------------------------------------------------------------------------------+
| type          | str    | 证券类型；stock;future;bond;index;option;fund                                    |
+---------------+--------+----------------------------------------------------------------------------------+
| updated_at    | date   | 更新日期，本地parquet没有                                                        |
+---------------+--------+----------------------------------------------------------------------------------+
| source        | str    | 数据来源                                                                         |
+---------------+--------+----------------------------------------------------------------------------------+


================================================================================
分钟数据字典 (Minute Bar Data Dictionary)
================================================================================

以下字段说明适用于分钟数据表。

【字段说明表】

+---------------+--------+----------------------------------------------------------------------------------+
| 字段          | 类型   | 说明                                                                             |
+===============+========+==================================================================================+
| symbol        | str    | 证券代码                                                                         |
+---------------+--------+----------------------------------------------------------------------------------+
| dt            | date   | 交易日期                                                                         |
+---------------+--------+----------------------------------------------------------------------------------+
| ts            | datetime| 交易时间                                                                        |
+---------------+--------+----------------------------------------------------------------------------------+
| open          | float  | 开盘价                                                                           |
+---------------+--------+----------------------------------------------------------------------------------+
| high          | float  | 最高价                                                                           |
+---------------+--------+----------------------------------------------------------------------------------+
| low           | float  | 最低价                                                                           |
+---------------+--------+----------------------------------------------------------------------------------+
| close         | float  | 收盘价                                                                           |
+---------------+--------+----------------------------------------------------------------------------------+
| volume        | float  | 成交量                                                                           |
+---------------+--------+----------------------------------------------------------------------------------+
| amount        | float  | 成交额                                                                           |
+---------------+--------+----------------------------------------------------------------------------------+
| open_interest | float  | 持仓量；除了期权期货外，其他品种为空                                             |
+---------------+--------+----------------------------------------------------------------------------------+
| settle        | float  | 结算价；除了期权期货外，其他品种为空                                             |
+---------------+--------+----------------------------------------------------------------------------------+
| type          | str    | 证券类型；stock;future;bond;index;option;fund                                    |
+---------------+--------+----------------------------------------------------------------------------------+
| update_at     | date   | 更新日期，本地parquet没有                                                        |
+---------------+--------+----------------------------------------------------------------------------------+
| source        | str    | 数据来源                                                                         |
+---------------+--------+----------------------------------------------------------------------------------+
"""


# ================================================================================
# 数据刷新功能实现
# ================================================================================

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

api_data_path = Path(r"\data\api_data")
getrich_data_path = Path(r"F:\getrich_data")

# ================================================================================
# Insight 数据转换辅助函数
# ================================================================================


def convert_insight_exchange(exchange_code: str) -> str:
    """
    将 Insight exchange 列代码转换为 Miller 标准交易所代码

    Insight exchange 列 -> Miller 代码:
    - XSHG -> SH (上交所)
    - XSHE -> SZ (深交所)
    - XBSE -> BJ (北交所)
    - XSGE -> SHF (上期所)
    - XDCE -> DCE (大商所)
    - XZCE -> CZC (郑商所)
    - XGFE -> GFE (广期所)
    - CCFX -> CFE (中金所)
    - INE -> INE (能源所)
    """
    exchange_map = {
        "XSHG": "SH",
        "XSHE": "SZ",
        "XBSE": "BJ",
        "XSGE": "SHF",
        "XDCE": "DCE",
        "XZCE": "CZC",
        "XGFE": "GFE",
        "CCFX": "CFE",
        "INE": "INE",
    }
    return exchange_map.get(exchange_code, exchange_code)


def convert_insight_symbol(htsc_code: str, exchange: str) -> str:
    """
    将 Insight 证券代码转换为 Miller 标准代码格式

    Insight 格式: 600000.XSHG
    Miller 格式: 600000.SH
    """
    if "." in htsc_code:
        code, _ = htsc_code.rsplit(".", 1)
        return f"{code}.{convert_insight_exchange(exchange)}"
    return htsc_code


def parse_insight_date(date_val) -> str:
    """
    解析 Insight 日期格式为 yyyy-mm-dd
    处理多种可能的日期格式
    """
    if pd.isna(date_val) or date_val is None:
        return None
    if isinstance(date_val, str):
        # 尝试多种格式
        for fmt in ["%Y-%m-%d", "%Y%m%d", "%Y/%m/%d", "%d-%m-%Y"]:
            try:
                return datetime.strptime(date_val, fmt).strftime("%Y-%m-%d")
            except:
                continue
        return date_val[:10] if len(date_val) >= 10 else date_val
    elif isinstance(date_val, (datetime, pd.Timestamp)):
        return date_val.strftime("%Y-%m-%d")
    return str(date_val)[:10]


# ================================================================================
# RiceQuant 数据刷新
# ================================================================================

# 交易所代码映射: RiceQuant -> Miller
RICEQUANT_EXCHANGE_MAP = {
    # 股票交易所
    "XSHE": "SZ",
    "XSHG": "SH",
    "BJSE": "BJ",
    # 期货交易所
    "SHFE": "SHF",
    "CFFEX": "CFE",
    "CZCE": "CZC",
    "DCE": "DCE",
    "GFEX": "GFE",
    "INE": "INE",
}

# 证券信息资产类型配置
# (文件夹名, 所需字段列表, 是否有标的代码, 是否有期权特征)
SYMBOL_INFO_CONFIG = {
    "stock": {
        "folder": "股票",
        "columns": [
            "order_book_id",
            "symbol",
            "exchange",
            "listed_date",
            "de_listed_date",
        ],
        "has_underlying": False,
        "has_option_fields": False,
        "multiplier": 1,
    },
    "fund": {
        "folder": "ETF",
        "columns": [
            "order_book_id",
            "symbol",
            "exchange",
            "listed_date",
            "de_listed_date",
        ],
        "has_underlying": False,
        "has_option_fields": False,
        "multiplier": 1,
    },
    "index": {
        "folder": "指数",
        "columns": [
            "order_book_id",
            "symbol",
            "exchange",
            "listed_date",
            "de_listed_date",
        ],
        "has_underlying": False,
        "has_option_fields": False,
        "multiplier": 1,
    },
    "bond": {
        "folder": "债券",
        "columns": [
            "order_book_id",
            "symbol",
            "exchange",
            "listed_date",
            "de_listed_date",
        ],
        "has_underlying": False,
        "has_option_fields": False,
        "multiplier": 1,
    },
    "future": {
        "folder": "期货",
        "columns": [
            "order_book_id",
            "symbol",
            "exchange",
            "listed_date",
            "maturity_date",
            "contract_multiplier",
            "underlying_order_book_id",
            "underlying_symbol",
        ],
        "has_underlying": True,
        "has_option_fields": False,
        "multiplier": None,  # 从数据读取
    },
    "option": {
        "folder": "期权",
        "columns": [
            "order_book_id",
            "symbol",
            "exchange",
            "listed_date",
            "maturity_date",
            "contract_multiplier",
            "underlying_order_book_id",
            "underlying_symbol",
            "option_type",
            "strike_price",
        ],
        "has_underlying": True,
        "has_option_fields": True,
        "multiplier": None,  # 从数据读取
    },
}

# 日线数据资产类型配置
DAILY_BAR_CONFIG = {
    "stock": {"folder": "股票", "has_oi_settle": False},
    "fund": {"folder": "ETF", "has_oi_settle": False},
    "index": {"folder": "指数", "has_oi_settle": False},
    "bond": {"folder": "可转债", "has_oi_settle": False},
    "future": {"folder": "期货", "has_oi_settle": True},
    "option": {"folder": "期权", "has_oi_settle": True},
}

# 分钟数据资产类型配置
MINUTE_BAR_CONFIG = {
    "stock": {"folder": "股票", "has_oi_settle": False},
    "fund": {"folder": "ETF", "has_oi_settle": False},
    "index": {"folder": "指数", "has_oi_settle": False},
    "bond": {"folder": "可转债", "has_oi_settle": False},
    "future": {"folder": "期货", "has_oi_settle": True},
    "option": {"folder": "期权", "has_oi_settle": True},
}


def _convert_ricequant_symbol(symbol: str) -> str:
    """将 RiceQuant symbol 转换为 Miller 格式"""
    if pd.isna(symbol):
        return symbol
    # 替换交易所后缀
    for rq_code, miller_code in RICEQUANT_EXCHANGE_MAP.items():
        if symbol.endswith(f".{rq_code}"):
            return symbol.replace(f".{rq_code}", f".{miller_code}")
    return symbol


def _convert_ricequant_exchange(exchange: str) -> str:
    """将 RiceQuant 交易所代码转换为 Miller 格式"""
    return RICEQUANT_EXCHANGE_MAP.get(exchange, exchange)


def _process_ricequant_symbol_info(
    tempdata: pd.DataFrame, asset: str, date: str
) -> pd.DataFrame:
    """
    处理 RiceQuant 证券信息数据

    字段映射:
    - order_book_id -> symbol (证券代码)
    - symbol -> name (证券名称)
    - exchange -> exchange (交易所)
    - listed_date -> listed_date (上市日期)
    - de_listed_date/maturity_date -> delisted_date (退市/到期日期)
    - contract_multiplier -> multiplier (合约乘数)
    - underlying_order_book_id -> und_code (标的代码)
    - underlying_symbol -> und_name (标的名称)
    - option_type -> optiontype (期权类型: C->call, P->put)
    - strike_price -> strike (行权价)
    """
    config = SYMBOL_INFO_CONFIG[asset]

    # 选择可用列
    available_cols = [c for c in config["columns"] if c in tempdata.columns]
    tempdata = tempdata[available_cols].copy()

    # 列重命名
    rename_map = {
        "order_book_id": "symbol",
        "symbol": "name",
        "de_listed_date": "delisted_date",
        "maturity_date": "delisted_date",
        "contract_multiplier": "multiplier",
        "underlying_order_book_id": "und_code",
        "underlying_symbol": "und_name",
        "option_type": "optiontype",
        "strike_price": "strike",
    }
    tempdata = tempdata.rename(columns=rename_map)

    # 转换交易所代码（必须先处理，因为 symbol 补齐依赖 exchange）
    if "exchange" in tempdata.columns:
        tempdata["exchange"] = tempdata["exchange"].apply(_convert_ricequant_exchange)

    # 转换 symbol 格式
    if "symbol" in tempdata.columns:
        # 对于期货和期权，如果 symbol 没有交易所后缀，利用 exchange 列补齐
        if asset in ["future", "option"]:

            def complete_symbol_with_exchange(row):
                sym = row["symbol"]
                if pd.isna(sym):
                    return sym
                # 如果已经有后缀，进行标准转换
                has_suffix = False
                for rq_code, miller_code in RICEQUANT_EXCHANGE_MAP.items():
                    if str(sym).endswith(f".{rq_code}"):
                        return str(sym).replace(f".{rq_code}", f".{miller_code}")
                    if "." in str(sym):
                        has_suffix = True
                # 如果没有后缀，利用 exchange 列补齐
                if not has_suffix and "exchange" in row and pd.notna(row["exchange"]):
                    return f"{sym}.{row['exchange']}"
                return sym

            tempdata["symbol"] = tempdata.apply(complete_symbol_with_exchange, axis=1)
        else:
            # 股票等其他类型使用原有转换逻辑
            tempdata["symbol"] = tempdata["symbol"].apply(_convert_ricequant_symbol)

    # 转换标的代码格式（期货和期权同样处理补齐逻辑）
    if "und_code" in tempdata.columns and config["has_underlying"]:
        if asset in ["future", "option"]:

            def complete_und_code(row):
                und = row["und_code"]
                if pd.isna(und):
                    return und
                # 如果已经有后缀，进行标准转换
                for rq_code, miller_code in RICEQUANT_EXCHANGE_MAP.items():
                    if str(und).endswith(f".{rq_code}"):
                        return str(und).replace(f".{rq_code}", f".{miller_code}")
                # 期货标的（如 CU2503）需要从 symbol 中提取交易所信息
                if asset == "future" and "symbol" in row and pd.notna(row["symbol"]):
                    sym = row["symbol"]
                    if "." in str(sym):
                        exchange = str(sym).rsplit(".", 1)[1]
                        return f"{und}.{exchange}"
                return und

            tempdata["und_code"] = tempdata.apply(complete_und_code, axis=1)
        else:
            tempdata["und_code"] = tempdata["und_code"].apply(_convert_ricequant_symbol)

    # 添加固定字段
    tempdata["dt"] = date
    tempdata["source"] = "ricequant"
    tempdata["type"] = asset

    # 设置标的代码和名称（如果没有）
    if not config["has_underlying"]:
        tempdata["und_code"] = tempdata["symbol"]
        tempdata["und_name"] = tempdata["name"]
    else:
        if "und_code" not in tempdata.columns:
            tempdata["und_code"] = None
        if "und_name" not in tempdata.columns:
            tempdata["und_name"] = None

    # 设置期权字段
    if config["has_option_fields"]:
        # 转换期权类型
        if "optiontype" in tempdata.columns:
            tempdata["optiontype"] = tempdata["optiontype"].map(
                {"C": "call", "P": "put", "c": "call", "p": "put"}
            )
    else:
        tempdata["optiontype"] = None
        tempdata["strike"] = None

    # 设置合约乘数
    if config["multiplier"] is not None:
        tempdata["multiplier"] = config["multiplier"]
    elif "multiplier" not in tempdata.columns:
        tempdata["multiplier"] = 1

    # 设置默认退市日期
    if "delisted_date" not in tempdata.columns:
        tempdata["delisted_date"] = "2099-12-31"

    # 确保列顺序一致
    output_cols = [
        "symbol",
        "dt",
        "exchange",
        "name",
        "type",
        "und_code",
        "und_name",
        "optiontype",
        "strike",
        "multiplier",
        "listed_date",
        "delisted_date",
        "source",
    ]
    # 只保留存在的列
    output_cols = [c for c in output_cols if c in tempdata.columns]
    tempdata = tempdata[output_cols]

    return tempdata


def _process_ricequant_daily_bar(
    tempdata: pd.DataFrame,
    asset: str,
    has_oi_settle: bool,
    symbol_info: pd.DataFrame = None,
) -> pd.DataFrame:
    """
    处理 RiceQuant 日线数据

    字段映射:
    - order_book_id -> symbol (证券代码)
    - date -> dt (交易日期)
    - open -> open (开盘价)
    - high -> high (最高价)
    - low -> low (最低价)
    - close -> close (收盘价)
    - volume -> volume (成交量)
    - total_turnover -> amount (成交额)
    - settlement -> settle (结算价，期货期权)
    - open_interest -> open_interest (持仓量，期货期权)

    Parameters:
        tempdata: 原始数据
        asset: 资产类型
        has_oi_settle: 是否有持仓量和结算价
        symbol_info: 证券信息数据，用于补齐 symbol 后缀（仅用于期货和期权）
    """
    # 基础列
    base_columns = [
        "order_book_id",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "total_turnover",
    ]
    if has_oi_settle:
        base_columns.extend(["settlement", "open_interest"])

    # 选择可用列
    available_cols = [c for c in base_columns if c in tempdata.columns]
    tempdata = tempdata[available_cols].copy()

    # 列重命名
    rename_map = {
        "order_book_id": "symbol",
        "date": "dt",
        "total_turnover": "amount",
        "settlement": "settle",
    }
    tempdata = tempdata.rename(columns=rename_map)

    # 转换 symbol 格式
    if "symbol" in tempdata.columns:
        # 对于期货和期权，利用证券信息列表补齐 symbol 后缀
        if (
            asset in ["future", "option"]
            and symbol_info is not None
            and not symbol_info.empty
        ):
            # 创建纯代码 -> 完整代码的映射
            symbol_mapping = {}
            for _, row in symbol_info.iterrows():
                full_symbol = row["symbol"]
                if isinstance(full_symbol, str) and "." in full_symbol:
                    pure_code = full_symbol.rsplit(".", 1)[0]
                    symbol_mapping[pure_code] = full_symbol

            def complete_daily_symbol(sym):
                if pd.isna(sym):
                    return sym
                # 如果已经有后缀，进行标准转换
                for rq_code, miller_code in RICEQUANT_EXCHANGE_MAP.items():
                    if str(sym).endswith(f".{rq_code}"):
                        return str(sym).replace(f".{rq_code}", f".{miller_code}")
                # 如果没有后缀，从证券信息映射中获取
                if "." not in str(sym):
                    return symbol_mapping.get(sym, sym)
                return sym

            tempdata["symbol"] = tempdata["symbol"].apply(complete_daily_symbol)
        else:
            # 股票等其他类型使用原有转换逻辑
            tempdata["symbol"] = tempdata["symbol"].apply(_convert_ricequant_symbol)

    # 添加空字段（如果不是期货期权）
    if not has_oi_settle:
        tempdata["open_interest"] = None
        tempdata["settle"] = None

    # 添加类型和数据源
    tempdata["type"] = asset
    tempdata["source"] = "ricequant"

    # 确保列顺序
    output_cols = [
        "symbol",
        "dt",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "open_interest",
        "settle",
        "type",
        "source",
    ]
    output_cols = [c for c in output_cols if c in tempdata.columns]
    tempdata = tempdata[output_cols]

    return tempdata


def _process_ricequant_minute_bar(
    tempdata: pd.DataFrame,
    asset: str,
    has_oi_settle: bool,
    symbol_info: pd.DataFrame = None,
) -> pd.DataFrame:
    """
    处理 RiceQuant 分钟数据

    字段映射:
    - order_book_id -> symbol (证券代码)
    - datetime -> ts (交易时间)
    - trading_date -> dt (交易日期)
    - open -> open (开盘价)
    - high -> high (最高价)
    - low -> low (最低价)
    - close -> close (收盘价)
    - volume -> volume (成交量)
    - total_turnover -> amount (成交额)
    - open_interest -> open_interest (持仓量，期货期权)

    Parameters:
        tempdata: 原始数据
        asset: 资产类型
        has_oi_settle: 是否有持仓量和结算价
        symbol_info: 证券信息数据，用于补齐 symbol 后缀（仅用于期货和期权）
    """
    # 基础列
    base_columns = [
        "order_book_id",
        "datetime",
        "trading_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "total_turnover",
    ]
    if has_oi_settle:
        base_columns.append("open_interest")

    # 选择可用列
    available_cols = [c for c in base_columns if c in tempdata.columns]
    tempdata = tempdata[available_cols].copy()

    # 列重命名
    rename_map = {
        "order_book_id": "symbol",
        "datetime": "ts",
        "trading_date": "dt",
        "total_turnover": "amount",
    }
    tempdata = tempdata.rename(columns=rename_map)

    # 转换 symbol 格式
    if "symbol" in tempdata.columns:
        # 对于期货和期权，利用证券信息列表补齐 symbol 后缀
        if (
            asset in ["future", "option"]
            and symbol_info is not None
            and not symbol_info.empty
        ):
            # 创建纯代码 -> 完整代码的映射
            symbol_mapping = {}
            for _, row in symbol_info.iterrows():
                full_symbol = row["symbol"]
                if isinstance(full_symbol, str) and "." in full_symbol:
                    pure_code = full_symbol.rsplit(".", 1)[0]
                    symbol_mapping[pure_code] = full_symbol

            def complete_minute_symbol(sym):
                if pd.isna(sym):
                    return sym
                # 如果已经有后缀，进行标准转换
                for rq_code, miller_code in RICEQUANT_EXCHANGE_MAP.items():
                    if str(sym).endswith(f".{rq_code}"):
                        return str(sym).replace(f".{rq_code}", f".{miller_code}")
                # 如果没有后缀，从证券信息映射中获取
                if "." not in str(sym):
                    return symbol_mapping.get(sym, sym)
                return sym

            tempdata["symbol"] = tempdata["symbol"].apply(complete_minute_symbol)
        else:
            # 股票等其他类型使用原有转换逻辑
            tempdata["symbol"] = tempdata["symbol"].apply(_convert_ricequant_symbol)

    # 处理日期格式
    if "dt" in tempdata.columns:
        # 从 datetime 字符串提取日期部分
        tempdata["dt"] = pd.to_datetime(tempdata["dt"]).dt.strftime("%Y-%m-%d")

    # 处理时间戳
    if "ts" in tempdata.columns:
        tempdata["ts"] = pd.to_datetime(tempdata["ts"])

    # 添加空字段（如果不是期货期权）
    if not has_oi_settle:
        tempdata["open_interest"] = None

    # 添加 settle 字段（分钟数据通常没有结算价）
    tempdata["settle"] = None

    # 添加类型和数据源
    tempdata["type"] = asset
    tempdata["source"] = "ricequant"

    # 确保列顺序
    output_cols = [
        "symbol",
        "dt",
        "ts",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "open_interest",
        "settle",
        "type",
        "source",
    ]
    output_cols = [c for c in output_cols if c in tempdata.columns]
    tempdata = tempdata[output_cols]

    return tempdata


def refresh_ricequant_data(data_type: str, date: str):
    """
    重构 RiceQuant 数据

    Parameters:
        data_type: 数据类型，可选 '证券信息', '日线数据', '分钟数据'
        date: 日期字符串，格式 'yyyy-mm-dd'
    """
    if data_type == "证券信息":
        _refresh_ricequant_symbol_info(date)
    elif data_type == "日线数据":
        _refresh_ricequant_daily_data(date)
    elif data_type == "分钟数据":
        _refresh_ricequant_minute_data(date)
    else:
        raise ValueError(f"未知的数据类型: {data_type}")


def _refresh_ricequant_symbol_info(date: str):
    """重构 RiceQuant 证券信息数据"""
    rice_data_path = api_data_path / "ricequant_data" / "证券信息"

    for asset, config in SYMBOL_INFO_CONFIG.items():
        input_file = rice_data_path / config["folder"] / f"{date}.parquet"
        output_folder = getrich_path / "证券信息" / config["folder"]

        if not input_file.exists():
            print(f"[RiceQuant] 证券信息文件不存在: {input_file}")
            continue

        if not output_folder.exists():
            output_folder.mkdir(parents=True)

        try:
            # 读取数据
            tempdata = pd.read_parquet(input_file)

            # 处理数据
            tempdata = _process_ricequant_symbol_info(tempdata, asset, date)

            # 保存数据
            output_file = output_folder / f"{date}.parquet"
            tempdata.to_parquet(output_file, index=False, engine="pyarrow")
            print(f"[RiceQuant] 已保存证券信息: {output_file}")

        except Exception as e:
            print(f"[RiceQuant] 处理 {asset} 证券信息时出错: {e}")


def _refresh_ricequant_daily_data(date: str):
    """重构 RiceQuant 日线数据"""
    rice_data_path = api_data_path / "ricequant_data" / "日线数据"

    # 预加载期货和期权的证券信息数据（用于补齐 symbol 后缀）
    # 优先从 miller_data 读取已处理的证券信息，如果没有则从原始数据生成
    symbol_info_cache = {}
    for asset in ["future", "option"]:
        # 首先尝试从已处理的 miller_data 读取
        symbol_info_file = (
            miller_data_path
            / "证券信息"
            / DAILY_BAR_CONFIG[asset]["folder"]
            / f"{date}.parquet"
        )
        if symbol_info_file.exists():
            try:
                symbol_info_cache[asset] = pd.read_parquet(symbol_info_file)
            except Exception as e:
                print(f"[RiceQuant] 读取 {asset} 证券信息失败: {e}")
                symbol_info_cache[asset] = None
        else:
            # 尝试从 api_data 读取原始证券信息并处理
            raw_symbol_info_file = (
                api_data_path
                / "ricequant_data"
                / "证券信息"
                / DAILY_BAR_CONFIG[asset]["folder"]
                / f"{date}.parquet"
            )
            if raw_symbol_info_file.exists():
                try:
                    raw_symbol_info = pd.read_parquet(raw_symbol_info_file)
                    # 处理原始证券信息数据，补齐 symbol 后缀
                    symbol_info_cache[asset] = _process_ricequant_symbol_info(
                        raw_symbol_info, asset, date
                    )
                except Exception as e:
                    print(f"[RiceQuant] 读取 {asset} 原始证券信息失败: {e}")
                    symbol_info_cache[asset] = None
            else:
                symbol_info_cache[asset] = None

    for asset, config in DAILY_BAR_CONFIG.items():
        input_file = rice_data_path / config["folder"] / f"{date}.parquet"
        output_folder = getrich_path / "日线数据" / config["folder"]

        if not input_file.exists():
            print(f"[RiceQuant] 日线数据文件不存在: {input_file}")
            continue

        if not output_folder.exists():
            output_folder.mkdir(parents=True)

        try:
            # 读取数据
            tempdata = pd.read_parquet(input_file)

            # 获取证券信息（用于期货和期权补齐 symbol 后缀）
            symbol_info = (
                symbol_info_cache.get(asset) if asset in ["future", "option"] else None
            )

            # 处理数据
            tempdata = _process_ricequant_daily_bar(
                tempdata, asset, config["has_oi_settle"], symbol_info
            )

            # 保存数据
            output_file = output_folder / f"{date}.parquet"
            tempdata.to_parquet(output_file, index=False, engine="pyarrow")
            print(f"[RiceQuant] 已保存日线数据: {output_file}")

        except Exception as e:
            print(f"[RiceQuant] 处理 {asset} 日线数据时出错: {e}")


def _refresh_ricequant_minute_data(date: str):
    """重构 Rice Quant 分钟数据"""
    rice_data_path = api_data_path / "ricequant_data" / "分钟数据"

    # 预加载期货和期权的证券信息数据（用于补齐 symbol 后缀）
    # 优先从 miller_data 读取已处理的证券信息，如果没有则从原始数据生成
    symbol_info_cache = {}
    for asset in ["future", "option"]:
        # 首先尝试从已处理的 miller_data 读取
        symbol_info_file = (
            miller_data_path
            / "证券信息"
            / MINUTE_BAR_CONFIG[asset]["folder"]
            / f"{date}.parquet"
        )
        if symbol_info_file.exists():
            try:
                symbol_info_cache[asset] = pd.read_parquet(symbol_info_file)
            except Exception as e:
                print(f"[RiceQuant] 读取 {asset} 证券信息失败: {e}")
                symbol_info_cache[asset] = None
        else:
            # 尝试从 api_data 读取原始证券信息并处理
            raw_symbol_info_file = (
                api_data_path
                / "ricequant_data"
                / "证券信息"
                / MINUTE_BAR_CONFIG[asset]["folder"]
                / f"{date}.parquet"
            )
            if raw_symbol_info_file.exists():
                try:
                    raw_symbol_info = pd.read_parquet(raw_symbol_info_file)
                    # 处理原始证券信息数据，补齐 symbol 后缀
                    symbol_info_cache[asset] = _process_ricequant_symbol_info(
                        raw_symbol_info, asset, date
                    )
                except Exception as e:
                    print(f"[RiceQuant] 读取 {asset} 原始证券信息失败: {e}")
                    symbol_info_cache[asset] = None
            else:
                symbol_info_cache[asset] = None

    for asset, config in MINUTE_BAR_CONFIG.items():
        input_file = rice_data_path / config["folder"] / f"{date}.parquet"
        output_folder = getrich_path / "分钟数据" / config["folder"]

        if not input_file.exists():
            print(f"[RiceQuant] 分钟数据文件不存在: {input_file}")
            continue

        if not output_folder.exists():
            output_folder.mkdir(parents=True)

        try:
            # 读取数据
            tempdata = pd.read_parquet(input_file)

            # 获取证券信息（用于期货和期权补齐 symbol 后缀）
            symbol_info = (
                symbol_info_cache.get(asset) if asset in ["future", "option"] else None
            )

            # 处理数据
            tempdata = _process_ricequant_minute_bar(
                tempdata, asset, config["has_oi_settle"], symbol_info
            )

            # 保存数据
            output_file = output_folder / f"{date}.parquet"
            tempdata.to_parquet(output_file, index=False, engine="pyarrow")
            print(f"[RiceQuant] 已保存分钟数据: {output_file}")

        except Exception as e:
            print(f"[RiceQuant] 处理 {asset} 分钟数据时出错: {e}")


# ================================================================================
# Insight 数据刷新
# ================================================================================


def refresh_insight_symbol_info(date: str, data_type: str = "证券信息"):
    """
    重构 Insight 数据
    从 api_data/insight_data 读取各类型数据，转换为 miller_data 格式

    Parameters:
        date: 日期字符串，格式 'yyyy-mm-dd'
        data_type: 数据类型，可选 '证券信息', '日线数据', '分钟数据'
    """
    if data_type == "证券信息":
        _refresh_insight_symbol_info_impl(date)
    elif data_type == "日线数据":
        _refresh_insight_daily_data(date)
    elif data_type == "分钟数据":
        _refresh_insight_minute_data(date)
    else:
        raise ValueError(f"未知的数据类型: {data_type}")


def _refresh_insight_symbol_info_impl(date: str):
    """
    重构 Insight 证券信息数据
    从 api_data/insight_data/证券信息 读取各类型数据，转换为 miller_data 格式
    """
    insight_data_path = api_data_path / "insight_data" / "证券信息"

    # 资产类型映射: {miller_type: (insight_folder, insight_type_code)}
    asset_mapping = {
        "stock": ("股票", "stock"),
        "bond": ("可转债", "bond"),
        "fund": ("ETF", "fund"),
        "index": ("指数", "index"),
        "future": ("期货", "future"),
        "option": ("期权", "option"),
    }

    for miller_type, (insight_folder, _) in asset_mapping.items():
        input_file = insight_data_path / insight_folder / f"{date}.parquet"
        output_folder = getrich_path / "证券信息" / insight_folder

        if not input_file.exists():
            print(f"[Insight] 文件不存在: {input_file}")
            continue

        if not output_folder.exists():
            output_folder.mkdir(parents=True)

        # 读取 Insight 数据
        tempdata = pd.read_parquet(input_file)

        if miller_type == "stock":
            tempdata = _process_insight_stock(tempdata, date)
        elif miller_type == "bond":
            tempdata = _process_insight_bond(tempdata, date)
        elif miller_type == "fund":
            tempdata = _process_insight_fund(tempdata, date)
        elif miller_type == "index":
            tempdata = _process_insight_index(tempdata, date)
        elif miller_type == "future":
            tempdata = _process_insight_future(tempdata, date)
        elif miller_type == "option":
            tempdata = _process_insight_option(tempdata, date)

        # 统一列顺序
        tempdata = tempdata[
            [
                "symbol",
                "dt",
                "exchange",
                "name",
                "type",
                "und_code",
                "und_name",
                "optiontype",
                "strike",
                "multiplier",
                "listed_date",
                "delisted_date",
                "source",
            ]
        ]

        # 保存到 miller_data
        tempdata.to_parquet(
            output_folder / f"{date}.parquet", index=False, engine="pyarrow"
        )
        print(f"[Insight] 已保存证券信息: {output_folder / f'{date}.parquet'}")


def _refresh_insight_daily_data(date: str):
    """
    重构 Insight 日线数据
    从 api_data/insight_data/日线数据 读取各类型数据，转换为 miller_data 格式
    """
    insight_data_path = api_data_path / "insight_data" / "日线数据"

    # 资产类型映射: {miller_type: (insight_folder, has_oi_settle)}
    # has_oi_settle: 是否含有持仓量和结算价字段（期货期权有，其他没有）
    asset_mapping = {
        "stock": ("股票", False),
        "bond": ("可转债", False),
        "fund": ("ETF", False),
        "index": ("指数", False),
        "future": ("期货", True),
        "option": ("期权", True),
    }

    for miller_type, (insight_folder, has_oi_settle) in asset_mapping.items():
        input_file = insight_data_path / insight_folder / f"{date}.parquet"
        output_folder = getrich_path / "日线数据" / insight_folder

        if not input_file.exists():
            print(f"[Insight] 日线数据文件不存在: {input_file}")
            continue

        if not output_folder.exists():
            output_folder.mkdir(parents=True)

        # 读取 Insight 数据
        tempdata = pd.read_parquet(input_file)

        # 处理 Insight 日线数据
        tempdata = _process_insight_daily_bar(
            tempdata, date, miller_type, has_oi_settle
        )

        # 统一列顺序
        tempdata = tempdata[
            [
                "symbol",
                "dt",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "open_interest",
                "settle",
                "type",
                "source",
            ]
        ]

        # 保存到 miller_data
        tempdata.to_parquet(
            output_folder / f"{date}.parquet", index=False, engine="pyarrow"
        )
        print(f"[Insight] 已保存日线数据: {output_folder / f'{date}.parquet'}")


def _refresh_insight_minute_data(date: str):
    """
    重构 Insight 分钟数据
    从 api_data/insight_data/分钟数据 读取各类型数据，转换为 miller_data 格式
    """
    insight_data_path = api_data_path / "insight_data" / "分钟数据"

    # 资产类型映射: {miller_type: (insight_folder, has_oi_settle)}
    # has_oi_settle: 是否含有持仓量和结算价字段（期货期权有，其他没有）
    asset_mapping = {
        "stock": ("股票", False),
        "bond": ("可转债", False),
        "fund": ("ETF", False),
        "index": ("指数", False),
        "future": ("期货", True),
        "option": ("期权", True),
    }

    for miller_type, (insight_folder, has_oi_settle) in asset_mapping.items():
        input_file = insight_data_path / insight_folder / f"{date}.parquet"
        output_folder = getrich_path / "分钟数据" / insight_folder

        if not input_file.exists():
            print(f"[Insight] 分钟数据文件不存在: {input_file}")
            continue

        if not output_folder.exists():
            output_folder.mkdir(parents=True)

        # 读取 Insight 数据
        tempdata = pd.read_parquet(input_file)

        # 处理 Insight 分钟数据
        tempdata = _process_insight_minute_bar(
            tempdata, date, miller_type, has_oi_settle
        )

        # 统一列顺序
        tempdata = tempdata[
            [
                "symbol",
                "dt",
                "ts",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "open_interest",
                "settle",
                "type",
                "source",
            ]
        ]

        # 保存到 miller_data
        tempdata.to_parquet(
            output_folder / f"{date}.parquet", index=False, engine="pyarrow"
        )
        print(f"[Insight] 已保存分钟数据: {output_folder / f'{date}.parquet'}")


def _process_insight_daily_bar(
    tempdata: pd.DataFrame, date: str, miller_type: str, has_oi_settle: bool
) -> pd.DataFrame:
    """
    处理 Insight 日线行情数据

    Insight字段 -> Miller字段:
    - htsc_code -> symbol (证券代码)
    - time -> dt (交易日期)
    - open -> open (开盘价)
    - close -> close (收盘价)
    - high -> high (最高价)
    - low -> low (最低价)
    - volume -> volume (成交量)
    - value -> amount (成交额)
    - open_interest -> open_interest (持仓量，期货期权才有)
    - settle -> settle (结算价，期货期权才有)
    """
    # 选择需要的列
    base_columns = [
        "htsc_code",
        "time",
        "open",
        "close",
        "high",
        "low",
        "volume",
        "value",
    ]
    if has_oi_settle:
        base_columns.extend(["open_interest", "settle"])

    available_cols = [c for c in base_columns if c in tempdata.columns]
    tempdata = tempdata[available_cols].copy()

    # 重命名列
    rename_map = {"htsc_code": "symbol", "time": "dt", "value": "amount"}
    tempdata = tempdata.rename(columns=rename_map)

    # 处理 symbol: 从 htsc_code 格式转换为 Miller 格式
    # Insight格式: 600000.XSHG -> Miller格式: 600000.SH
    if "symbol" in tempdata.columns:
        tempdata["symbol"] = tempdata["symbol"].apply(_convert_insight_htsc_code)

    # 处理 dt 字段
    if "dt" in tempdata.columns:
        # Insight的time可能是datetime格式，需要转换为date格式
        tempdata["dt"] = pd.to_datetime(tempdata["dt"]).dt.strftime("%Y-%m-%d")
    else:
        # 如果没有time列，使用传入的date参数
        tempdata["dt"] = date

    # 添加期货期权特有的字段（如果没有）
    if "open_interest" not in tempdata.columns:
        tempdata["open_interest"] = None
    if "settle" not in tempdata.columns:
        tempdata["settle"] = None

    # 添加类型和数据源标识
    tempdata["type"] = miller_type
    tempdata["source"] = "insight"

    return tempdata


def _process_insight_minute_bar(
    tempdata: pd.DataFrame, date: str, miller_type: str, has_oi_settle: bool
) -> pd.DataFrame:
    """
    处理 Insight 分钟行情数据

    Insight字段 -> Miller字段:
    - htsc_code -> symbol (证券代码)
    - time -> ts (交易时间，datetime格式)
    - open -> open (开盘价)
    - close -> close (收盘价)
    - high -> high (最高价)
    - low -> low (最低价)
    - volume -> volume (成交量)
    - value -> amount (成交额)
    - open_interest -> open_interest (持仓量，期货期权才有)
    - settle -> settle (结算价，期货期权才有)
    - dt 从 ts 中提取（交易日期）
    """
    # 选择需要的列
    base_columns = [
        "htsc_code",
        "time",
        "open",
        "close",
        "high",
        "low",
        "volume",
        "value",
    ]
    if has_oi_settle:
        base_columns.extend(["open_interest", "settle"])

    available_cols = [c for c in base_columns if c in tempdata.columns]
    tempdata = tempdata[available_cols].copy()

    # 重命名列
    rename_map = {"htsc_code": "symbol", "time": "ts", "value": "amount"}
    tempdata = tempdata.rename(columns=rename_map)

    # 处理 symbol: 从 htsc_code 格式转换为 Miller 格式
    if "symbol" in tempdata.columns:
        tempdata["symbol"] = tempdata["symbol"].apply(_convert_insight_htsc_code)

    # 处理 ts 字段，确保是datetime格式
    if "ts" in tempdata.columns:
        tempdata["ts"] = pd.to_datetime(tempdata["ts"])
        # 从 ts 提取 dt (交易日期)
        tempdata["dt"] = tempdata["ts"].dt.strftime("%Y-%m-%d")
    else:
        # 如果没有time列，使用传入的date参数
        tempdata["ts"] = pd.to_datetime(date)
        tempdata["dt"] = date

    # 添加期货期权特有的字段（如果没有）
    if "open_interest" not in tempdata.columns:
        tempdata["open_interest"] = None
    if "settle" not in tempdata.columns:
        tempdata["settle"] = None

    # 添加类型和数据源标识
    tempdata["type"] = miller_type
    tempdata["source"] = "insight"

    return tempdata


def _convert_insight_htsc_code(htsc_code: str) -> str:
    """
    将 Insight htsc_code 转换为 Miller symbol 格式

    Insight symbol 后缀 -> Miller 后缀:
    - .SH -> .SH (上交所)
    - .SZ -> .SZ (深交所)
    - .BJ -> .BJ (北交所)
    - .SHF -> .SHF (上期所)
    - .DCE -> .DCE (大商所)
    - .ZCE -> .CZC (郑商所)
    - .GFE -> .GFE (广期所)
    - .CF -> .CFE (中金所)
    - .INE -> .INE (能源所)
    """
    if pd.isna(htsc_code):
        return htsc_code

    htsc_code = str(htsc_code)
    if "." not in htsc_code:
        return htsc_code

    code, suffix = htsc_code.rsplit(".", 1)

    # Insight symbol 后缀映射到 Miller 格式
    suffix_map = {
        "SH": "SH",
        "SZ": "SZ",
        "BJ": "BJ",
        "SHF": "SHF",
        "DCE": "DCE",
        "ZCE": "CZC",  # 郑商所
        "GFE": "GFE",
        "CF": "CFE",  # 中金所
        "INE": "INE",
    }

    miller_suffix = suffix_map.get(suffix, suffix)
    return f"{code}.{miller_suffix}"


def _process_insight_stock(tempdata: pd.DataFrame, date: str) -> pd.DataFrame:
    """处理 Insight 股票数据"""
    columns_needed = ["htsc_code", "name", "exchange", "listing_date"]
    available_cols = [c for c in columns_needed if c in tempdata.columns]
    tempdata = tempdata[available_cols].copy()

    tempdata = tempdata.rename(
        columns={
            "htsc_code": "symbol",
            "name": "name",
            "exchange": "exchange",
            "listing_date": "listed_date",
        }
    )

    # 转换 exchange 列
    tempdata["exchange"] = tempdata["exchange"].apply(convert_insight_exchange)
    # 转换 symbol 列（使用 symbol 后缀映射）
    tempdata["symbol"] = tempdata["symbol"].apply(_convert_insight_htsc_code)

    tempdata["dt"] = date
    tempdata["source"] = "insight"
    tempdata["type"] = "stock"
    tempdata["und_code"] = tempdata["symbol"]
    tempdata["und_name"] = tempdata["name"]
    tempdata["optiontype"] = None
    tempdata["strike"] = None
    tempdata["multiplier"] = 1
    tempdata["delisted_date"] = "2099-12-31"

    if "listed_date" in tempdata.columns:
        tempdata["listed_date"] = tempdata["listed_date"].apply(parse_insight_date)

    return tempdata


def _process_insight_bond(tempdata: pd.DataFrame, date: str) -> pd.DataFrame:
    """处理 Insight 可转债数据"""
    columns_needed = [
        "htsc_code",
        "name",
        "exchange",
        "exchange_code",
        "listing_date",
        "convert_code",
        "convert_abbr",
    ]
    available_cols = [c for c in columns_needed if c in tempdata.columns]
    tempdata = tempdata[available_cols].copy()

    tempdata = tempdata.rename(
        columns={
            "htsc_code": "symbol",
            "name": "name",
            "listing_date": "listed_date",
            "convert_code": "und_code",
            "convert_abbr": "und_name",
        }
    )

    # 处理 exchange 列
    if "exchange" in tempdata.columns:
        tempdata["exchange"] = tempdata["exchange"].apply(convert_insight_exchange)
    elif "exchange_code" in tempdata.columns:
        tempdata["exchange"] = tempdata["exchange_code"].apply(convert_insight_exchange)
    else:
        tempdata["exchange"] = tempdata["symbol"].apply(
            lambda x: "SH" if ".SH" in str(x) else ("SZ" if ".SZ" in str(x) else "BJ")
        )

    # 转换 symbol 列（使用 symbol 后缀映射）
    tempdata["symbol"] = tempdata["symbol"].apply(_convert_insight_htsc_code)

    # 处理正股代码（同样使用 symbol 后缀映射）
    if "und_code" in tempdata.columns:
        tempdata["und_code"] = tempdata["und_code"].apply(_convert_insight_htsc_code)

    tempdata["dt"] = date
    tempdata["source"] = "insight"
    tempdata["type"] = "bond"
    if "und_code" not in tempdata.columns:
        tempdata["und_code"] = tempdata["symbol"]
    if "und_name" not in tempdata.columns:
        tempdata["und_name"] = tempdata["name"]
    tempdata["optiontype"] = None
    tempdata["strike"] = None
    tempdata["multiplier"] = 1
    tempdata["delisted_date"] = "2099-12-31"

    if "listed_date" in tempdata.columns:
        tempdata["listed_date"] = tempdata["listed_date"].apply(parse_insight_date)

    return tempdata


def _process_insight_fund(tempdata: pd.DataFrame, date: str) -> pd.DataFrame:
    """处理 Insight ETF 数据"""
    columns_needed = ["htsc_code", "name", "exchange", "listing_date"]
    available_cols = [c for c in columns_needed if c in tempdata.columns]
    tempdata = tempdata[available_cols].copy()

    tempdata = tempdata.rename(
        columns={
            "htsc_code": "symbol",
            "name": "name",
            "exchange": "exchange",
            "listing_date": "listed_date",
        }
    )

    # 转换 exchange 列
    tempdata["exchange"] = tempdata["exchange"].apply(convert_insight_exchange)
    # 转换 symbol 列（使用 symbol 后缀映射）
    tempdata["symbol"] = tempdata["symbol"].apply(_convert_insight_htsc_code)

    tempdata["dt"] = date
    tempdata["source"] = "insight"
    tempdata["type"] = "fund"
    tempdata["und_code"] = tempdata["symbol"]
    tempdata["und_name"] = tempdata["name"]
    tempdata["optiontype"] = None
    tempdata["strike"] = None
    tempdata["multiplier"] = 1
    tempdata["delisted_date"] = "2099-12-31"

    if "listed_date" in tempdata.columns:
        tempdata["listed_date"] = tempdata["listed_date"].apply(parse_insight_date)

    return tempdata


def _process_insight_index(tempdata: pd.DataFrame, date: str) -> pd.DataFrame:
    """处理 Insight 指数数据"""
    columns_needed = ["htsc_code", "name", "exchange"]
    available_cols = [c for c in columns_needed if c in tempdata.columns]
    tempdata = tempdata[available_cols].copy()

    tempdata = tempdata.rename(
        columns={"htsc_code": "symbol", "name": "name", "exchange": "exchange"}
    )

    # 转换 exchange 列
    tempdata["exchange"] = tempdata["exchange"].apply(convert_insight_exchange)
    # 转换 symbol 列（使用 symbol 后缀映射）
    tempdata["symbol"] = tempdata["symbol"].apply(_convert_insight_htsc_code)

    tempdata["dt"] = date
    tempdata["source"] = "insight"
    tempdata["type"] = "index"
    tempdata["und_code"] = tempdata["symbol"]
    tempdata["und_name"] = tempdata["name"]
    tempdata["optiontype"] = None
    tempdata["strike"] = None
    tempdata["multiplier"] = 1
    tempdata["listed_date"] = None
    tempdata["delisted_date"] = "2099-12-31"

    return tempdata


def _process_insight_future(tempdata: pd.DataFrame, date: str) -> pd.DataFrame:
    """处理 Insight 期货数据"""
    columns_needed = [
        "htsc_code",
        "name",
        "exchange",
        "listing_date",
        "expire_date",
        "product_id",
        "instrument_name",
        "volume_multiple",
    ]
    available_cols = [c for c in columns_needed if c in tempdata.columns]
    tempdata = tempdata[available_cols].copy()

    tempdata = tempdata.rename(
        columns={
            "htsc_code": "symbol",
            "name": "name",
            "exchange": "exchange",
            "listing_date": "listed_date",
            "expire_date": "delisted_date",
            "product_id": "und_code",
            "instrument_name": "und_name",
            "volume_multiple": "multiplier",
        }
    )

    # 转换 exchange 列
    tempdata["exchange"] = tempdata["exchange"].apply(convert_insight_exchange)
    # 转换 symbol 列（使用 symbol 后缀映射）
    tempdata["symbol"] = tempdata["symbol"].apply(_convert_insight_htsc_code)

    tempdata["dt"] = date
    tempdata["source"] = "insight"
    tempdata["type"] = "future"

    if "multiplier" in tempdata.columns:
        tempdata["multiplier"] = pd.to_numeric(
            tempdata["multiplier"], errors="coerce"
        ).fillna(1)
    else:
        tempdata["multiplier"] = 1

    if "und_code" not in tempdata.columns or tempdata["und_code"].isna().all():
        tempdata["und_code"] = (
            tempdata["symbol"]
            .str.replace(r"\.\w+$", "", regex=True)
            .str.replace(r"\d+", "", regex=True)
        )

    if "und_name" not in tempdata.columns:
        tempdata["und_name"] = tempdata["name"]

    tempdata["optiontype"] = None
    tempdata["strike"] = None

    if "listed_date" in tempdata.columns:
        tempdata["listed_date"] = tempdata["listed_date"].apply(parse_insight_date)
    if "delisted_date" in tempdata.columns:
        tempdata["delisted_date"] = tempdata["delisted_date"].apply(parse_insight_date)
    else:
        tempdata["delisted_date"] = None

    return tempdata


def _process_insight_option(tempdata: pd.DataFrame, date: str) -> pd.DataFrame:
    """处理 Insight 期权数据"""
    columns_needed = [
        "htsc_code",
        "name",
        "exchange",
        "listing_date",
        "option_end_date",
        "option_underlying_security_id",
        "option_underlying_symbol",
        "option_call_or_put",
        "option_exercise_price",
        "option_contract_multiplier_unit",
    ]
    available_cols = [c for c in columns_needed if c in tempdata.columns]
    tempdata = tempdata[available_cols].copy()

    tempdata = tempdata.rename(
        columns={
            "htsc_code": "symbol",
            "name": "name",
            "exchange": "exchange",
            "listing_date": "listed_date",
            "option_end_date": "delisted_date",
            "option_underlying_security_id": "und_code",
            "option_underlying_symbol": "und_name",
            "option_call_or_put": "optiontype",
            "option_exercise_price": "strike",
            "option_contract_multiplier_unit": "multiplier",
        }
    )

    # 转换 exchange 列
    tempdata["exchange"] = tempdata["exchange"].apply(convert_insight_exchange)
    # 转换 symbol 列（使用 symbol 后缀映射）
    tempdata["symbol"] = tempdata["symbol"].apply(_convert_insight_htsc_code)

    # 转换标的代码（同样使用 symbol 后缀映射）
    if "und_code" in tempdata.columns:
        tempdata["und_code"] = tempdata["und_code"].apply(
            lambda x: _convert_insight_htsc_code(x) if pd.notna(x) else x
        )

    tempdata["dt"] = date
    tempdata["source"] = "insight"
    tempdata["type"] = "option"

    if "optiontype" in tempdata.columns:
        tempdata["optiontype"] = tempdata["optiontype"].map(
            {"C": "call", "P": "put", "c": "call", "p": "put"}
        )

    if "multiplier" in tempdata.columns:
        tempdata["multiplier"] = pd.to_numeric(
            tempdata["multiplier"], errors="coerce"
        ).fillna(10000)
    else:
        tempdata["multiplier"] = 10000

    if "strike" in tempdata.columns:
        tempdata["strike"] = pd.to_numeric(tempdata["strike"], errors="coerce")
    else:
        tempdata["strike"] = None

    if "listed_date" in tempdata.columns:
        tempdata["listed_date"] = tempdata["listed_date"].apply(parse_insight_date)
    if "delisted_date" in tempdata.columns:
        tempdata["delisted_date"] = tempdata["delisted_date"].apply(parse_insight_date)

    return tempdata


def refresh_insight_data(data_type: str, date: str):
    """
    重构 Insight 数据的主入口函数
    data_type: 证券信息；日线数据；分钟数据
    """
    if data_type in ["证券信息", "日线数据", "分钟数据"]:
        refresh_insight_symbol_info(date, data_type)
    else:
        raise ValueError(f"未知的数据类型: {data_type}")


if __name__ == "__main__":
    # 测试 RiceQuant 数据刷新
    # 证券信息
    # refresh_ricequant_data("证券信息", "2025-01-06")

    # 日线数据
    refresh_ricequant_data("日线数据", "2025-01-06")

    # 分钟数据
    refresh_ricequant_data("分钟数据", "2025-01-06")

    # 测试 Insight 数据刷新
    # 证券信息
    # refresh_insight_data("证券信息", "2025-01-06")

    # 日线数据
    # refresh_insight_data("日线数据", "2025-01-06")

    # 分钟数据
    # refresh_insight_data("分钟数据", "2025-01-06")
