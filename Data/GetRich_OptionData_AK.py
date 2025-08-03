"""
从akshare获取期权数据
Author: QiuZiHua
Date: 2025/08/01
"""
import akshare as ak
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

# 1. 获取指定标的，指定到期日的当天正在交易的期权合约列表
def get_option_list(symbol, end_month):
    """
    获取指定标的，指定到期日的当天正在交易的期权合约列表
    symbol= 指定标的,华泰柏瑞沪深300ETF期权,上证50股指期权
    end_month="2509";    """
    df = ak.option_finance_board(symbol=symbol, end_month=end_month)
    return df

# 2. 获取所有期权实时行情，包含金融期权和商品期权-东财
def get_option_realtime():
    """
    获取所有期权实时行情，包含金融期权和商品期权-东财
    """
    df = ak.option_current_em()
    return df

# 3. 获取股指期权到期日列表
def get_option_index_end_month(symbol):
    """
    symbol="上证50, 沪深300,中证1000";
    """
    if symbol == "上证50":
        df = ak.option_cffex_sz50_list_sina()
    elif symbol == "沪深300":
        df = ak.option_cffex_hs300_list_sina()
    elif symbol == "中证1000":
        df = ak.option_cffex_zz1000_list_sina()

    return df

# 4. 获取股指期权实时行情
def get_option_index_realtime(symbol, end_month):
    """
    symbol="上证50, 沪深300,中证1000";
    end_month：从get_option_index_end_month获取的到期月份
    """
    if symbol == "上证50":
        df = ak.option_cffex_sz50_spot_sina(symbol=end_month)
    elif symbol == "沪深300":
        df = ak.option_cffex_hs300_spot_sina(symbol=end_month)
    elif symbol == "中证1000":
        df = ak.option_cffex_zz1000_spot_sina(symbol=end_month)
    return df

# 5. 获取股指期权日频行情
def get_option_index_daily(symbol):
    """
    symbol= 合约代码，可以从get_option_index_realtime获取
    """
    if symbol == "上证50":
        df = ak.option_cffex_sz50_daily_sina(symbol=symbol)
    elif symbol == "沪深300":
        df = ak.option_cffex_hs300_daily_sina(symbol=symbol)
    elif symbol == "中证1000":
        df = ak.option_cffex_zz1000_daily_sina(symbol=symbol)
    return df


# 6. 获取期权行情分时数据-东财
def get_option_minute_em(symbol):
    """
    symbol= 合约代码，可以从get_option_realtime获取
    """
    df = ak.option_minute_em(symbol=symbol)
    return df

# 7. ETF期权风险分析-金融期权-东财
def get_option_ETF_risk_analysis_em():
    """
    期权风险分析-金融期权-东财
    """
    df = ak.option_risk_analysis_em()
    return df

# 8. ETF期权折溢价-金融期权-东财
def get_option_ETF_discount_em():
    """
    ETF期权折溢价-金融期权-东财
    """
    df = ak.option_premium_analysis_em()
    return df

# 9. 商品期权当日交易合约-新浪
def get_option_commodity_contract_current(symbol):
    """
    symbol= "玉米期权"
    """
    df = ak.option_commodity_contract_sina(symbol=symbol)
    return df

# 10. 商品期权当日交易合约T型报价-新浪
def get_option_commodity_contract_current_T(symbol):
    """
    symbol= "玉米期权"
    """
    df = ak.option_commodity_contract_table_sina(symbol=symbol)
    return df

# 11. 历史行情-新浪
def get_option_commodity_contract_history(symbol):
    """
    symbol="au2012C328"; 可以通过 get_option_commodity_contract_current 获取具体合约代码
    """
    df = ak.option_commodity_hist_sina(symbol=symbol)
    return df

# 12. 商品期权保证金
def get_option_commodity_margin(symbol):
    """
    symbol="原油"; 可以通过 ak.option_margin_symbol() 所有 symbol
    """
    df = ak.option_margin(symbol=symbol)
    return df

# 13. 获取上海期货交易所日频期权数据
def get_option_shfe_daily(symbol, trade_date):
    """
    symbol	str	symbol="铜期权"; choice of {'原油期权', '铜期权', '铝期权', '锌期权', '铅期权',
    '螺纹钢期权', '镍期权', '锡期权', '氧化铝期权', '黄金期权', '白银期权', '丁二烯橡胶期权', '天胶期权'}
    trade_date	str	trade_date="20191017"
    """
    df = ak.option_shfe_daily(symbol=symbol)
    return df

# 14. 获取大连商品交易所日频期权数据
def get_option_dce_daily(symbol, trade_date):
    """
    symbol    str    symbol="玉米期权";
    trade_date    str    trade_date="20191017"
    """
    df = ak.option_dce_daily(symbol=symbol)
    return df


# 15. 获取广州期货交易所日频期权数据
def get_option_gfex_daily(symbol, trade_date):
    """
    symbol    str    symbol="工业硅"; choice of {"工业硅", "碳酸锂"}
    trade_date    str    trade_date="20241017"
    """
    df = ak.option_gfex_daily(symbol=symbol, trade_date=trade_date)
    return df

# 16. 获取广州期货交易所日频隐含波动率
def get_option_gfex_iv(symbol, trade_date):
    """
    symbol    str    symbol="工业硅"; choice of {"工业硅", "碳酸锂"}
    trade_date    str    trade_date="20241017"
    """
    df = ak.option_gfex_vol_daily(symbol=symbol, trade_date=trade_date)
    return df

# 17. 获取郑州商品期货交易所日频期权数据
def get_option_zce_daily(symbol, year):
    """
    year	str	year="2019"; 指定年份
    symbol	str	symbol="SR"; choice of {"白糖": "SR",
    "棉花": "CF", "PTA": "TA", "甲醇": "MA", "菜籽粕": "RM",
    "动力煤": "ZC", "菜籽油": "OI", "花生": "PK",
    "对二甲苯": "PX", "烧碱": "SH", "纯碱": "SA",
    "短纤": "PF", "锰硅": "SM", "硅铁": "SF", "尿素": "UR",
     "苹果": "AP", "红枣": "CJ", "玻璃": "FG", "瓶片": "PR"}
    """
    df = ak.option_czce_hist(symbol=symbol, year=year)
    return df






if __name__ == '__main__':
    # print(get_option_list(symbol="上证50股指期权", end_month="2509"))
    # print(get_option_realtime())
    # print(get_option_ETF_risk_analysis_em())
    # print(get_option_ETF_discount_em())
    # print(get_option_commodity_contract_current(symbol="玉米期权"))
    # print(get_option_commodity_contract_current_T(symbol="黄金期权"))
    # print(get_option_commodity_contract_history(symbol="au2012C328"))
    # print(get_option_commodity_margin(symbol="原油期权"))
    # print(get_option_shfe_daily(symbol="铜期权", trade_date="20241017"))
    # print(get_option_dce_daily(symbol="玉米期权", trade_date="20241017"))
    # print(get_option_gfex_daily(symbol="工业硅", trade_date="20241017"))
    # print(get_option_gfex_iv(symbol="工业硅", trade_date="20241017"))
    print(get_option_zce_daily(symbol="SR", year="2024"))


