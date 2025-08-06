"""
从AKShare获取指数数据
Author: QiuZihua
Date: 2025/08/04
"""

import akshare as ak
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

# 1. A股股票指数-实时行情-东财
def get_index_spot_realtime_em(symbol):
    """
    获取A股股票指数-实时行情-东财
    symbol	str	symbol="上证系列指数"；choice of {"沪深重要指数", "上证系列指数", "深证系列指数", "指数成份", "中证系列指数"}
    """
    df = ak.stock_zh_index_spot_em(symbol=symbol)
    return df

# 2. A股股票指数实时行情-新浪
def get_index_spot_realtime_sina():
    """
    获取A股股票指数-实时行情-新浪
    """
    df = ak.stock_zh_index_spot_sina()
    return df

# 3. 获取股票指数历史行情-新浪
def get_index_spot_history_sina(symbol, period, start_date, end_date):
    """
    获取股票指数历史行情-新浪
    symbol	str	symbol="sh000001"; 指数代码, 例如: sh000001 代表上证指数
    """
    df = ak.stock_zh_index_daily(symbol=symbol)
    return df

# 4. 获取历史行情数据-东财
def get_index_spot_history_em(symbol):
    """
    获取股票指数历史行情-东财
    symbol	str	symbol="sz399552"; 支持 sz: 深交所, sh: 上交所, csi: 中证指数 + id(000905)
    start_date	str	start_date="19900101"
    end_date	str	end_date="20500101"
    """
    df = ak.stock_zh_index_daily_em(symbol=symbol)
    return df

# 5. 获取指数历史行情数据-指定区间内
def get_index_spot_history(symbol, period, start_date, end_date):
    """
    获取指数历史行情数据
    symbol	str	symbol="399282"; 指数代码，此处不用市场标识
    period	str	period="daily"; choice of {'daily', 'weekly', 'monthly'}
    start_date	str	start_date="19700101"; 开始日期
    end_date	str	end_date="22220101"; 结束时间
    """
    df = ak.index_zh_a_hist(symbol=symbol, period=period, start_date=start_date, end_date=end_date)
    return df

# 6. 获取指数分时行情数据-东财
def get_index_spot_minute_em(symbol, period, start_date, end_date):
    """
    获取指数分时行情数据-东财
    symbol	str	symbol="399006"; 指数代码，此处不用市场标识
    period	str	period="1"; choice of {'1', '5', '15', '30', '60'}, 其中 1 分钟数据只能返回当前的, 其余只能返回近期的数据
    start_date	str	start_date="1979-09-01 09:32:00"; 开始日期时间
    end_date	str	end_date="2222-01-01 09:32:00"; 结束时间时间
    """
    df = ak.index_zh_a_hist_min_em(symbol=symbol, period=period, start_date=start_date, end_date=end_date)
    return df


# 7. 港股股票指数-实时行情-新浪
def get_index_hk_realtime_sina():
    """
    获取港股股票指数-实时行情-新浪
    """
    df = ak.stock_hk_index_spot_sina()
    return df

# 8. 港股股票指数-历史行情-新浪
def get_index_hk_history_sina(symbol):
    """
    获取港股股票指数-历史行情-新浪
    symbol="CES100"; 代码从get_index_hk_realtime_sina()获取
    """
    df = ak.stock_hk_index_daily_sina(symbol=symbol)
    return df


# 9. 港股股票指数-实时行情-东财
def get_index_hk_realtime_em():
    """
    获取港股股票指数-实时行情-东财
    """
    df = ak.stock_hk_index_spot_em()
    return df

# 10. 港股股票指数-历史行情-东财
def get_index_hk_history_em(symbol):
    """
    获取港股股票指数-历史行情-东财
    symbol=symbol="HSTECF2L"; 代码从get_index_hk_realtime_em()获取
    """
    df = ak.stock_hk_index_daily_em(symbol=symbol)
    return df

# 11. 获取A股指数信息
def get_index_info_em():
    """
    获取A股指数信息
    """
    df = ak.index_stock_info()
    return df

# 12. 获取A股指数成份股
def get_index_stock_em(symbol):
    """
    获取A股指数成份股
    symbol=str	symbol="000001"; 指数代码, 例如: 000001 代表上证指数,代码从get_index_info_em()获取
    """
    df = ak.index_stock_cons(symbol=symbol)
    return df


# 13. 获取中证指数估值
def get_index_zz_valuation(symbol, start_date, end_date):
    """
    获取中证指数估值
    symbol	str	symbol="000928"; 指数代码
    start_date	str	start_date="20180526"
    end_date	str	end_date="20240604"
    """
    df = ak.stock_zh_index_hist_csindex(symbol=symbol, start_date=start_date, end_date=end_date)
    return df

# 14. 申万指数实时行情
def get_index_sw_realtime(symbol):
    """
    申万指数实时行情
    symbol	str	symbol="基础一级"; choice of {"基础一级", "基础二级", "基础三级", "特色指数"}
    """
    df = ak.index_realtime_fund_sw()
    return df

# 15. 申万基金指数历史行情
def get_index_sw_history(symbol, period):
    """
    申万指数历史行情
    symbol	str	symbol="807200"; 基金指数代码
    period	str	period="day"; choice of {"day", "week", "month"}
    """
    df = ak.index_hist_fund_sw(symbol=symbol, period=period)
    return df

# 16. 申万指数实时行情-sw
def get_index_sw_realtime_sw(symbol):
    """
    申万指数实时行情-sw
    symbol	str	symbol="市场表征"; choice of {"市场表征", "一级行业", "二级行业", "风格指数", "大类风格指数", "金创指数"}
    """
    df = ak.index_realtime_sw(symbol=symbol)
    return df

# 17. 申万指数历史行情-sw
def get_index_sw_history_sw(symbol, period):
    """
    申万指数历史行情-sw
    symbol    str    symbol="807200"; 基金指数代码
    period    str    period="day"; choice of {"day", "week", "month"}
    """
    df = ak.index_hist_sw(symbol=symbol, period=period)
    return df


# 18. 申万指数分时行情
def get_index_sw_minute(symbol):
    """
    申万指数分时行情
    symbol	str	symbol="801030"; 指数代码
    """
    df = ak.index_min_sw(symbol=symbol)
    return df

# 19. 申万指数成分股
def get_index_sw_stock(symbol):
    """
    申万指数成分股
    symbol    str    symbol="801030"; 指数代码
    """
    df = ak.index_component_sw(symbol=symbol)
    return df


# 20. 申万指数-日报表
def get_index_sw_daily_report(symbol, start_date, end_date):
    """
    申万指数-日报表
    symbol	str	symbol="市场表征"; choice of {"市场表征", "一级行业", "二级行业", "风格指数"}
    start_date	str	start_date="20221103"
    end_date	str	end_date="20221103"
    """
    df = ak.index_analysis_daily_sw(symbol=symbol, start_date=start_date, end_date=end_date)
    return df










# if __name__ == "__main__":
    # print(get_index_info_em())
    # print(get_index_stock_em("000300"))
    # print(get_index_zz_valuation("000300", "20180526", "20250805"))



























