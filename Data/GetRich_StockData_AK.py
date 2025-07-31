"""
从 akshare 获取数据
"""
import akshare as ak
import pandas as pd

# 1. 个股信息查询-雪球
def get_stock_info(symbol):
    """
    获取个股信息
    :param symbol: 股票代码 SH601127
    :return: 个股信息
    """
    stock_info_df = ak.stock_individual_basic_info_xq(symbol=symbol)
    return stock_info_df

# 2. 行情报价-东方财富
def get_stock_quote(symbol):
    """
    获取个股行情报价
    :param symbol: 股票代码 000001
    :return: 个股行情报价
    """
    stock_quote_df = ak.stock_bid_ask_em(symbol=symbol)
    return stock_quote_df

# 3. 实时行情数据-东方财富
def get_stock_realtime_quotes(dataapi='em'):
    """
    获取个股实时行情数据
    :param dataapi: 数据来源  em: 东方财富; sina: 新浪财经
    :return: A股市场所有个股实时行情数据
    """
    if dataapi == 'em':
        df = ak.stock_zh_a_spot_em()
        return df
    elif dataapi == 'sina':
        df = ak.stock_zh_a_spot()
        return df

# 4. 沪市A股实时行情数据-东方财富
def get_stock_sh_realtime_quotes():
    """
    获取沪市A股实时行情数据
    :return: 沪市A股实时行情数据
    """
    stock_sh_realtime_quotes_df = ak.stock_sh_a_spot_em()
    return stock_sh_realtime_quotes_df

# 5. 深市A股实时行情数据-东方财富
def get_stock_sz_realtime_quotes():
    """
    获取深市A股实时行情数据
    :return: 深市A股实时行情数据
    """
    stock_sz_realtime_quotes_df = ak.stock_sz_a_spot_em()
    return stock_sz_realtime_quotes_df

# 6. 北交所实时行情数据-东方财富
def get_stock_bj_realtime_quotes():
    """
    获取北交所实时行情数据
    :return: 北交所实时行情数据
    """
    stock_bj_realtime_quotes_df = ak.stock_bj_a_spot_em()
    return stock_bj_realtime_quotes_df

# 7. 新股实时行情数据-东方财富
def get_stock_new_realtime_quotes():
    """
    获取新股实时行情数据
    :return: 新股实时行情数据
    """
    stock_new_realtime_quotes_df = ak.stock_new_a_spot_em()
    return stock_new_realtime_quotes_df

# 8. 创业板板实时行情数据-东方财富
def get_stock_cyb_realtime_quotes():
    """
    获取创业板板实时行情数据
    :return: 创业板板实时行情数据
    """
    stock_cyb_realtime_quotes_df = ak.stock_cy_a_spot_em()
    return stock_cyb_realtime_quotes_df

# 9. 科创板实时行情数据-东方财富
def get_stock_kcb_realtime_quotes():
    """
    获取科创板实时行情数据
    :return: 科创板实时行情数据
    """
    stock_kcb_realtime_quotes_df = ak.stock_kc_a_spot_em()
    return stock_kcb_realtime_quotes_df

# 10. 个股实时行情数据-雪球
def get_stock_xq_realtime_quotes(symbol):
    """
    获取个股实时行情数据
    :param symbol: symbol="SH600000"; 证券代码，可以是 A 股个股代码，A 股场内基金代码，A 股指数，美股代码, 美股指数
    :return: 个股实时行情数据
    """
    df =  ak.stock_individual_spot_xq(symbol=symbol)
    return df

# 11. 个股历史行情数据-东财
def get_stock_history_em(symbol=None, period='daily', start_date=None, end_date=None, adjust=""):
    """
    获取个股历史行情数据
    :param symbol: symbol='603777'; 股票代码可以在 get_stock_realtime_quotes(dataapi='em')获取
    :param period: period="daily"; choice of {'daily', 'weekly', 'monthly'}
    :param start_date: start_date="20190101"; 开始日期 format：YYYYMMDD
    :param end_date: end_date="20190901"; 结束日期 format：YYYYMMDD
    :param adjust: adjust="hfq"; choice of {'qfq', 'hfq'}
    :return: 个股历史行情数据
    """
    df = ak.stock_zh_a_hist(symbol=symbol, period=period, start_date=start_date, end_date=end_date, adjust=adjust)
    return df


# 12. 个股历史日度行情数据-新浪
def get_stock_history_sina(symbol=None, start_date=None, end_date=None, adjust=""):
    """
    获取个股历史行情数据
    :param symbol: symbol='sh600000';  股票代码可以在 get_stock_realtime_quotes(dataapi='sina')获取
    :param start_date: start_date="20190101"; 开始日期 format：YYYYMMDD
    :param end_date: end_date="20190901"; 结束日期 format：YYYYMMDD
    :param adjust: 默认返回不复权的数据; qfq: 返回前复权后的数据; hfq: 返回后复权后的数据; hfq-factor: 返回后复权因子; qfq-factor: 返回前复权因子
    :return: 个股历史行情数据
    """
    df = ak.stock_zh_a_daily(symbol=symbol, start_date=start_date, end_date=end_date, adjust=adjust)
    return df

# 13. 个股历史日度行情数据-腾讯
def get_stock_history_tencent(symbol=None, start_date=None, end_date=None, adjust=""):
    """
    获取个股历史行情数据
    :param symbol: symbol='sh600000';
    :param start_date: start_date="20190101"; 开始日期 format：YYYYMMDD
    :param end_date: end_date="20190901"; 结束日期 format：YYYYMMDD
    :param adjust: 默认返回不复权的数据; qfq: 返回前复权后的数据; hfq: 返回后复权后的数据;
    :return: 个股历史行情数据
    """
    df = ak.stock_zh_a_hist_tx(symbol=symbol, start_date=start_date, end_date=end_date, adjust=adjust)
    return df

# 14. 当前交易日的个股分钟数据-新浪
def get_stock_minute_sina(symbol=None, period='1', adjust=""):
    """
    获取个股分钟数据
    :param symbol: symbol='sh600000';  股票代码可以在 get_stock_realtime_quotes(dataapi='sina')获取
    :param period: period="1"; choice of {'1', '5', '15', '30', '60'}
    :param adjust: 默认返回不复权的数据; qfq: 返回前复权后的数据; hfq: 返回后复权后的数据;
    :return: 个股分钟数据
    """
    df = ak.stock_zh_a_minute(symbol=symbol, period=period, adjust=adjust)
    return df

# 15. 获取历史的个股分钟数据-东财
def get_stock_minute_em(symbol=None, start_date=None, end_date=None, period='1', adjust=""):
    """
    获取个股分钟数据
    :param symbol: symbol='000300';  股票代码可以在 get_stock_realtime_quotes(dataapi='em')获取
    :param start_date: start_date="1979-09-01 09:32:00"; 日期时间; 默认返回所有数据
    :param end_date: end_date="2222-01-01 09:32:00"; 日期时间; 默认返回所有数据
    :param period: period="1"; choice of {'1', '5', '15', '30', '60'}，其中1分钟只有5个交易日的数据
    :param adjust: adjust=''; choice of {'', 'qfq', 'hfq'}; '': 不复权, 'qfq': 前复权, 'hfq': 后复权, 其中 1 分钟数据返回近 5 个交易日数据且不复权
    :return: 个股分钟数据
    """
    df = ak.stock_zh_a_hist_min_em(symbol=symbol, start_date=start_date, end_date=end_date, period=period, adjust=adjust)
    return df


# 16. 日内分时个股行情数据-东财
def get_stock_intraday_em(symbol):
    """
    获取日内分时个股行情数据
    :param symbol: symbol='000001';  股票代码可以在 get_stock_realtime_quotes(dataapi='em')获取
    :return: 日内分时个股行情数据
    """
    df = ak.stock_intraday_em(symbol=symbol)
    return df

# 17. 日内分时个股行情数据-新浪
def get_stock_intraday_sina(symbol, date):
    """
    获取日内分时个股行情数据
    :param symbol: symbol='sh600000';  股票代码可以在 get_stock_realtime_quotes(dataapi='sina')获取
    :param date: date='20210809'; 日期
    :return: 日内分时个股行情数据;D 表示卖盘，U表示是买盘
    """
    df = ak.stock_intraday_sina(symbol=symbol, date=date)
    return df

# 18. 股票历史的盘前数据-东财
def get_stock_pre_min_em(symbol=None, start_time=None, end_time=None):
    """
    获取股票盘前数据
    :param symbol: symbol='000001';  股票代码可以在 get_stock_realtime_quotes(dataapi='em')获取
    :param start_time: start_time="09:00:00"; 时间; 默认返回所有数据
    :param end_time: end_time="15:40:00"; 时间; 默认返回所有数据
    :return: 单次返回指定 symbol 的最近一个交易日的股票分钟数据, 包含盘前分钟数据
    """
    df = ak.stock_zh_a_hist_pre_min_em(symbol=symbol, start_time=start_time, end_time=end_time)
    return df

# 19. 股票历史分笔数据-腾讯
def get_stock_tick_tencent(symbol):
    """
    获取股票历史分笔数据
    :param symbol: symbol='sh600000';
    描述: 每个交易日 16:00 提供当日数据; 如遇到数据缺失, 请使用 ak.stock_zh_a_tick_163() 接口(注意数据会有一定差异)
    :return: 单次返回最近交易日的历史分笔行情数据
    """
    df = ak.stock_zh_a_tick_tx_js(symbol=symbol)
    return df

# 20. 获取新浪每天最新的次新股最近交易日数据
def get_stock_new_stock_sina():
    """
    获取新浪每天最新的次新股最近交易日数据
    :return: 新股数据
    symbol object 新浪代码
    code object 股票代码
    name object 股票简称
    open float64 开盘价
    high float64 最高价
    low float64 最低价
    volume int64 成交量
    amount int64 成交额
    mktcap float64 市值
    turnoverratio float64 换手率
    """
    df = ak.stock_zh_a_new()
    return df


# 21. 获取A股指定交易日所有上市公司的新闻动态-东财
def get_stock_news_em(date):
    """
    获取A股指定交易日所有上市公司的新闻动态
    :param date: date='20210809'; 日期
    :return: A股指定交易日所有上市公司的新闻动态
    """
    df = ak.stock_gsrl_gsdt_em(date=date)
    return df

# 22. 获取A股新股数据当前交易日的行情数据-东财
def get_stock_new_stock_em():
    """
    获取A股新股数据当前交易日的行情数据
    :return: A股新股数据当前交易日的行情数据
    """
    df = ak.stock_zh_a_new_em()
    return df


# 23. 科创板实时行情数据-新浪
def get_stock_kcb_realtime_quotes_sina():
    """
    获取科创板实时行情数据
    :return: 科创板实时行情数据
    """
    df = ak.stock_zh_kcb_spot()
    return df


# 24. 科创板历史行情数据-新浪
def get_stock_kcb_history_sina(symbol, adjust=""):
    """
    获取科创板历史行情数据
    :param symbol: symbol='sh688001';  股票代码可以在 get_stock_realtime_quotes(dataapi='sina')获取
    :param adjust: 默认不复权的数据; qfq: 返回前复权后的数据; hfq: 返回后复权后的数据; hfq-factor: 返回后复权因子; qfq-factor: 返回前复权因子
    :return: 科创板历史行情数据
    date	object	-
    close	float64	收盘价
    high	float64	最高价
    low	float64	最低价
    open	float64	开盘价
    volume	float64	成交量(股)
    after_volume	float64	盘后量; 参见科创板盘后固定价格交易
    after_amount	float64	盘后额; 参见科创板盘后固定价格交易
    outstanding_share	float64	流通股本(股)
    turnover	float64	换手率=成交量(股)/流通股本(股

    """
    df = ak.stock_zh_kcb_daily(symbol=symbol, adjust=adjust)
    return df

# 25. 科创板公告-东财
def get_stock_kcb_report_em(from_page, to_page):
    """
    获取科创板公告
    :param from_page: from_page=1; 页码
    :param to_page: to_page=100; 页码
    :return: 科创板公告
    名称	类型	描述
    代码	object	-
    名称	object	-
    公告标题	object	-
    公告类型	object	-
    公告日期	object	-
    公告代码	object	本代码可以用来获取公告详情: http://data.eastmoney.com/notices/detail/688595/{替换到此处}.html
    """
    df = ak.stock_zh_kcb_report_em(from_page=from_page, to_page=to_page)
    return df

# 26. AH股实时行情数据-东财
def get_ah_realtime_spot_em():
    """
    获取AH股实时行情数据
    :return: AH股实时行情数据

    """
    df = ak.stock_zh_ah_spot_em()
    return df


# 27. 获取AH股的历史行情数据-腾讯
def get_ah_history_tencent(symbol, start_year, end_year, adjust=""):
    """
    获取AH股的历史行情数据
    :param symbol: symbol="02318"; 港股股票代码, 可以通过 get_stock_ah_name_tencent() 函数获取
    :param start_year="2000"; 开始年份
    :param end_year="2019"; 结束年份
    :param adjust: adjust=""; 默认为空不复权; 'qfq': 前复权, 'hfq': 后复权
    :return: AH股的历史行情数据
    """
    df = ak.stock_zh_ah_daily(symbol=symbol, start_year=start_year, end_year=end_year, adjust="")
    return df

# 28. 获取AH股名单-腾讯
def get_stock_ah_name_tencent():
    """
    获取AH股名单
    :return: AH股名单
    """
    df = ak.stock_zh_ah_name()
    return df


# 29. 美股实时行情数据-东财
def get_stock_us_realtime_quotes():
    """
    获取美股实时行情数据
    :return: 美股所有上市公司的实时行情数据
    序号	int64	-
    名称	object	-
    最新价	float64	注意单位: 美元
    涨跌额	float64	注意单位: 美元
    涨跌幅	float64	注意单位: %
    开盘价	float64	注意单位: 美元
    最高价	float64	注意单位: 美元
    最低价	float64	注意单位: 美元
    昨收价	float64	注意单位: 美元
    总市值	float64	注意单位: 美元
    市盈率	float64	-
    成交量	float64	-
    成交额	float64	注意单位: 美元
    振幅	float64	注意单位: %
    换手率	float64	注意单位: %
    代码	object	注意: 用来获取历史数据的代码
    """
    df = ak.stock_us_spot_em()
    return df

# 30. 获取美股实时行情数据-新浪
def get_stock_us_realtime_quotes_sina():
    """
    获取美股实时行情数据
    :return: 美股所有上市公司的实时行情数据，有延迟15分钟
    """
    df = ak.stock_us_spot()
    return df

# 31. 获取美股历史数据
def get_stock_us_history(symbol, period, start_date, end_date, adjust=""):
    """
    获取美股历史数据
    :param symbol: symbol="AAPL"; 美股股票代码, 可以通过 get_stock_us_realtime_quotes() 函数获取
    :param period: period="daily"; 可以选择 daily, weekly, monthly
    :param start_date: start_date="20150101"; 开始日期
    :param end_date: end_date="20250729"; 结束日期
    :param adjust: adjust=""; 默认为空不复权; 'qfq': 前复权, 'hfq': 后复权
    :return: 美股历史数据
    """
    df = ak.stock_us_hist(symbol=symbol, period=period, start_date=start_date, end_date=end_date, adjust=adjust)
    return df


# 32. 获取港股实时行情数据-东财
def get_stock_hk_realtime_quotes():
    """
    获取港股实时行情数据
    :return: 港股实时行情数据
    """
    df = ak.stock_hk_spot_em()
    return df

# 33. 获取港股主板实时行情数据-东财
def get_stock_hk_main_realtime_quotes():
    """
    获取港股主板实时行情数据
    :return: 港股主板实时行情数据
    """
    df = ak.stock_hk_main_board_spot_em()
    return df


# 34.获取港股分时数据-东财
def get_stock_hk_minute_em(symbol, period, start_date, end_date, adjust=""):
    """
    获取港股分时数据
    :param symbol: symbol="00700"; 港股股票代码, 可以通过 get_stock_hk_realtime_quotes() 函数获取
    :param period: period="1"; 可以选择 1, 5, 15, 30, 60；1分钟只有最近5个交易日
    :param start_date: "1979-09-01 09:32:00"; 日期时间; 默认返回所有数据
    :param end_date: "2222-01-01 09:32:00"; 日期时间; 默认返回所有数据
    :param adjust: adjust=''; choice of {'', 'qfq', 'hfq'}; '': 不复权, 'qfq': 前复权, 'hfq': 后复权, 其中 1 分钟数据返回近 5 个交易日数据且不复权
    :return: 港股分时数据
    """
    df = ak.stock_hk_hist_min_em(symbol=symbol, period=period, start_date=start_date, end_date=end_date, adjust=adjust)
    return df

# 35. 港股历史行情数据-东财
def get_stock_hk_history_em(symbol, period, start_date, end_date, adjust=""):
    """
    获取港股历史行情数据
    :param symbol: symbol="00700"; 港股股票代码, 可以通过 get_stock_hk_realtime_quotes() 函数获取
    :param period: period="daily"; 可以选择 daily, weekly, monthly
    :param start_date: start_date="20150101"; 开始日期
    :param end_date: end_date="20250729"; 结束日期
    :param adjust: adjust=""; 默认为空不复权; 'qfq': 前复权, 'hfq': 后复权
    :return: 港股历史行情数据
    """
    df = ak.stock_hk_hist(symbol=symbol, period=period, start_date=start_date, end_date=end_date, adjust=adjust)
    return df


# 36. 获取知名港股实时数据-东财
def get_stock_hk_famous_spot_em():
    """
    获取知名港股实时数据
    :return: 港股实时行情数据
    """
    df = ak.stock_hk_famous_spot_em()
    return df

# 37. 获取知名美股实时数据-东财
def get_stock_us_famous_spot_em():
    """
    获取知名美股实时数据
    :return: 美股实时行情数据
    """
    df = ak.stock_us_famous_spot_em()
    return df


# 38. A股机构调研统计-东财
def get_stock_jgdy_em(date):
    """
    获取A股机构调研统计
    :param date: date="20250729"; 日期
    :return: A股机构调研统计
    """
    df = ak.stock_jgdy_tj_em(date=date)
    return df

# 39. 股票质押市场概况
def get_stock_pledge_em():
    """
    获取股票质押市场概况
    :return: 股票质押市场概况
    """
    df = ak.stock_gpzy_profile_em()
    return df

# 40. 上市公司质押比例
def get_stock_pledge_ratio_em(date):
    """
    获取上市公司质押比例
    :param date: date="20250729";
    单次返回指定交易日的所有历史数据; 其中的交易日需要根据网站提供的为准; 请访问 http://data.eastmoney.com/gpzy/pledgeRatio.aspx 查询具体交易日
    :return: 上市公司质押比例
    """
    df = ak.stock_gpzy_pledge_ratio_em(date=date)
    return df

# 41. 重要股东股份质押明细
def get_stock_pledge_detail_em():
    """
    获取重要股东股份质押明细
    目标地址: https://data.eastmoney.com/gpzy/pledgeDetail.aspx
    描述: 东方财富网-数据中心-特色数据-股权质押-重要股东股权质押明细
    限量: 单次所有历史数据, 由于数据量比较大需要等待一定时间
    :return: 重要股东股份质押明细
    """
    df = ak.stock_gpzy_pledge_ratio_detail_em()
    return df

# 42. 质押机构分布统计-证券公司
def get_stock_pledge_company_em():
    """
    获取质押机构分布统计-证券公司
    :return: 质押机构分布统计-证券公司
    """
    df = ak.stock_gpzy_distribute_statistics_company_em()
    return df


# 43. 质押机构分布统计-银行
def get_stock_pledge_bank_em():
    """
    获取质押机构分布统计-银行
    :return: 质押机构分布统计-银行
    """
    df = ak.stock_gpzy_distribute_statistics_bank_em()
    return df


# 44. 行业质押比例
def get_industry_pledge_ratio_em():
    """
    获取行业质押比例
    :return: 行业质押比例
    """
    df = ak.stock_gpzy_industry_data_em()
    return df

# 45. 股票账户月度统计
def get_stock_account_month_em():
    """
    获取股票账户月度统计
    :return: 股票账户月度统计
    """
    df = ak.stock_account_statistics_em()
    return df

# 46. 分析师指数排行
def get_stock_analyst_index_em(year):
    """
    获取分析师指数排行
    :param year: year="2025"; 2025年
    :return: 分析师指数排行
    """
    df = ak.stock_analyst_rank_em(year=year)
    return df

# 47. 分析师预测详情
def get_stock_analyst_detail_em(analyst_id, indicator):
    """
    获取分析师预测详情
    analyst_id	str	analyst_id="11000257131"; 分析师ID, 从 get_stock_analyst_index 获取
    indicator	str	indicator="最新跟踪成分股"; 从 {"最新跟踪成分股", "历史跟踪成分股", "历史指数"} 中选择
    :return: 分析师预测详情
    """
    df = ak.stock_analyst_detail_em(analyst_id=analyst_id, indicator=indicator)
    return df

# 48. 股票评论热度
def get_stock_comment_hot_em():
    """
    获取股票评论热度
    :return: 股票评论热度
    """
    df = ak.stock_comment_em()
    return df

# 49. 股票评论热度-个股
def get_stock_comment_hot_detail_em(symbol):
    """
    获取股票评论热度-个股
    :param symbol: symbol="600000"; 股票代码
    :return: 股票评论热度-个股
    """
    df = ak.stock_comment_detail_zlkp_jgcyd_em(symbol=symbol)
    return df

# 50. 股票-东财用户关注度
def get_stock_user_attention_em(symbol):
    """
    获取股票-东财用户关注度
    :param symbol: symbol="600000"; 股票代码
    :return: 股票-东财用户关注度
    """
    df = ak.stock_comment_detail_scrd_focus_em(symbol=symbol)
    return df

# 51. 沪深港股通资金流向
def get_stock_hsgt_em():
    """
    获取沪深港股通资金流向
    :return: 沪深港股通资金流向
    交易日	object	-
    类型	object	-
    板块	object	-
    资金方向	object	-
    交易状态	int64	3 为收盘
    成交净买额	float64	注意单位: 亿元
    资金净流入	float64	注意单位: 亿元
    当日资金余额	float64	注意单位: 亿元
    上涨数	int64	-
    持平数	int64	-
    下跌数	int64	-
    相关指数	object	-
    指数涨跌幅	float64	注意单位: %

    """
    df = ak.stock_hsgt_fund_flow_summary_em()
    return df


# 52. 沪深港股通历史数据
def get_stock_hsgt_history_em(symbol):
    """
    获取沪深港股通历史数据
    :param symbol:symbol="北向资金"; choice of {"北向资金", "沪股通", "深股通", "南向资金", "港股通沪", "港股通深"}
    :return: 沪深港股通历史数据
    日期	object	-
    当日成交净买额	float64	注意单位: 亿元
    买入成交额	float64	注意单位: 亿元
    卖出成交额	float64	注意单位: 亿元
    历史累计净买额	float64	注意单位: 万亿元
    当日资金流入	float64	注意单位: 亿元
    当日余额	float64	注意单位: 亿元
    持股市值	float64	注意单位: 元
    领涨股	object	-
    领涨股-涨跌幅	float64	注意单位: %
    沪深300	float64	-
    沪深300-涨跌幅	float64	注意单位: %
    领涨股-代码	object	-
    """
    df = ak.stock_hsgt_hist_em(symbol=symbol)
    return df


# 53. 业绩报表
def get_stock_performance_em(date):
    """
    获取业绩报表
    date:date="20200331"; choice of {"XXXX0331", "XXXX0630", "XXXX0930", "XXXX1231"}; 从 20100331 开始
    :return: 业绩报表
    """
    df = ak.stock_yjbb_em(date=date)
    return df

# 54. 业绩快报
def get_stock_performance_fast_em(date):
    """
    获取业绩快报
    date:date="20200331"; choice of {"XXXX0331", "XXXX0630", "XXXX0930", "XXXX1231"}; 从 20100331 开始
    :return: 业绩快报
    """
    df = ak.stock_yjkb_em(date=date)
    return df

# 55. 业绩预告
def get_stock_performance_forecast_em(date):
    """
    获取业绩预告
    date:date="20200331"; choice of {"XXXX0331", "XXXX0630", "XXXX0930", "XXXX1231"}; 从 20100331 开始
    :return: 业绩预告
    """
    df = ak.stock_yjyg_em(date=date)
    return df

# 56. 资产负债表
def get_stock_balance_sheet_em(date):
    """
    获取资产负债表
    date:date="20200331"; choice of {"XXXX0331", "XXXX0630", "XXXX0930", "XXXX1231"}; 从 20100331 开始
    :return: 资产负债表
    """
    df = ak.stock_zcfz_em(date=date)
    return df

# 57. 资产负债表-北交所
def get_stock_balance_sheet_bj_em(date):
    """
    获取资产负债表-北交所
    date:date="20200331"; choice of {"XXXX0331", "XXXX0630", "XXXX0930", "XXXX1231"}; 从 20100331 开始
    :return: 资产负债表-北交所
    """
    df = ak.stock_zcfz_bj_em(date=date)
    return df

# 58. 利润表
def get_stock_income_statement_em(date):
    """
    获取利润表
    date:date="20200331"; choice of {"XXXX0331", "XXXX0630", "XXXX0930", "XXXX1231"}; 从 20100331 开始
    :return: 利润表
    """
    df = ak.stock_lrb_em(date=date)
    return df

# 59. 现金流量表
def get_stock_cash_flow_em(date):
    """
    获取现金流量表
    date:date="20200331"; choice of {"XXXX0331", "XXXX0630", "XXXX0930", "XXXX1231"}; 从 20100331 开始
    :return: 现金流量表
    """
    df = ak.stock_xjll_em(date=date)
    return df


# 60. 股东增减持
def get_stock_shareholder_em(symbol="全部"):
    """
    获取股东增减持
    symbol="全部"; choice of {"全部", "股东增持", "股东减持"}
    :return: 股东增减持
    """
    df = ak.stock_ggcg_em(symbol=symbol)
    return df

# 61. 分红配送
def get_stock_dividend_em(date):
    """
    获取分红配送
    date="20231231"; choice of {"XXXX0630", "XXXX1231"}; 从 19901231 开始
    :return: 分红配送
    """
    df = ak.stock_fhps_em(date=date)
    return df

# 62. 分红配送详情
def get_stock_dividend_detail_em(symbol):
    """
    获取分红配送详情
    symbol="600000"; 股票代码
    :return: 分红配送详情
    """
    df = ak.stock_fhps_detail_em(symbol=symbol)
    return df

# 63. 个股资金流
def get_stock_fund_flow_em(symbol="即时"):
    """
    获取个股资金流
    symbol="即时"; choice of {“即时”, "3日排行", "5日排行", "10日排行", "20日排行"}
    :return: 个股资金流
    """
    df = ak.stock_fund_flow_individual(symbol=symbol)
    return df

# 64. 概念资金流
def get_stock_concept_fund_flow_em(symbol="即时"):
    """
    获取概念资金流
    symbol="即时"; choice of {“即时”, "3日排行", "5日排行", "10日排行", "20日排行"}
    :return: 概念资金流
    """
    df = ak.stock_fund_flow_concept(symbol=symbol)
    return df

# 65. 行业资金流
def get_stock_industry_fund_flow_em(symbol="即时"):
    """
    获取行业资金流
    symbol="即时"; choice of {“即时”, "3日排行", "5日排行", "10日排行", "20日排行"}
    :return: 行业资金流
    """
    df = ak.stock_fund_flow_industry(symbol=symbol)
    return df

# 66. 大单追踪
def get_stock_big_order_em():
    """
    获取大单追踪
    :return: 大单追踪
    """
    df = ak.stock_fund_flow_big_deal()
    return df

# 67. 个股资金流
def get_stock_fund_flow_detail_em(symbol, market):
    """
    获取个股资金流
    symbol="600000"; 股票代码
    market="sh"; choice of {"sh", "sz","bj"}
    :return: 单次获取指定市场和股票的近 100 个交易日的资金流数据
    """
    df = ak.stock_individual_fund_flow(stock=symbol, market=market)
    return df

# 68. 个股资金流排名
def get_stock_fund_flow_rank_em(indicator):
    """
    获取个股资金流排名
    indicator="今日"; choice {"今日", "3日", "5日", "10日"}
    :return: 单次获取指定市场和股票的近 100 个交易日的资金流数据
    """
    df = ak.stock_individual_fund_flow_rank(indicator=indicator)
    return df

# 69. 大盘资金流
def get_stock_market_fund_flow_em():
    """
    获取大盘资金流
    :return: 大盘资金流
    """
    df = ak.stock_market_fund_flow()
    return df

# 70. 板块资金流
def get_sector_fund_flow_rank(indicator, sector_type):
    """
    获取板块资金流排名
    indicator="今日"; choice {"今日", "3日", "5日", "10日"}
    sector_type="行业资金流"; choice of {"行业资金流", "概念资金流", "地域资金流"}
    :return: 板块资金流排名
    """
    df = ak.stock_sector_fund_flow_rank(indicator=indicator, sector_type=sector_type)
    return df

# 71. 主力净流入排名
def get_stock_main_fund_flow_rank_em(symbol):
    """
    获取主力净流入排名
    symbol="全部股票"；choice of {"全部股票", "沪深A股", "沪市A股", "科创板", "深市A股", "创业板", "沪市B股", "深市B股"}
    :return: 主力净流入排名
    """
    df = ak.stock_main_fund_flow(symbol=symbol)
    return df

# 72. 筹码分布
def get_stock_capital_distribution_em(symbol, adjust):
    """
    获取筹码分布
    symbol="600000"; 股票代码
    adjust="hfq"; choice of {"qfq", "hfq"}
    :return: 筹码分布
    """
    df = ak.stock_cyq_em(symbol=symbol, adjust=adjust)
    return df

# 73. A股指定日期公告
def get_stock_announcement_em(date, symbol):
    """
    获取A股指定日期公告
    date="20250729"; 日期
    symbol = '财务报告'; choice of {"全部", "重大事项", "财务报告", "融资公告", "风险提示", "资产重组", "信息变更", "持股变动"}
    :return: A股指定日期公告
    """
    df = ak.stock_notice_report(symbol=symbol, date=date)
    return df

# 74. 港股财务指标
def get_stock_hk_finance_indicator_em(symbol, indicator):
    """
    获取港股财务指标
    symbol="00700"; 股票代码
    indicator="年度"; choice of {"年度", "报告期"}
    :return: 港股财务指标
    """
    df = ak.stock_financial_hk_analysis_indicator_em(symbol=symbol, indicator=indicator)
    return df

# 75. 美股财务指标
def get_stock_us_finance_indicator_em(symbol, indicator):
    """
    获取美股财务指标
    symbol="AAPL"; 股票代码
    indicator="年度"; choice of {"年度", "报告期"}
    :return: 美股财务指标
    """
    df = ak.stock_financial_us_analysis_indicator_em(symbol=symbol, indicator=indicator)
    return df

# 76. A股历史分红
def get_stock_dividend_history_em():
    """
    获取A股历史分红
    symbol="600000"; 股票代码
    :return: A股历史分红
    """
    df = ak.stock_history_dividend()
    return df


# 77. 股东数量
def get_stock_shareholder_num_em(symbol):
    """
    获取股东数量
    symbol=symbol="20230930"; choice of {"最新", 每个季度末}, 其中 每个季度末需要写成 20230930 格式
    :return: 股东数量
    """
    df = ak.stock_zh_a_gdhs(symbol=symbol)
    return df



# 78. 股票列表-A股
def get_stock_list_em(symbol, symbol_type=None):
    """
    获取股票列表
    symbol="sh"; choice of {"sh", "sz", "bj", "all"}
    :return: 股票列表
    """
    if symbol=='all':
        df = ak.stock_info_a_code_name()
        return df
    elif symbol=='sh':
        # symbol_type = "主板A股"; choice of {"主板A股", "主板B股", "科创板"}
        df = ak.stock_info_sh_name_code(symbol = symbol_type)
        return df
    elif symbol=='sz':
        # symbol_type = "A股列表"; choice of {"A股列表", "B股列表", "CDR列表", "AB股列表"}
        df = ak.stock_info_sz_name_code(symbol = symbol_type)
        return df
    elif symbol=='bj':
        df = ak.stock_info_bj_name_code()
        return df

# 79. 美股和港股的目标价格
def get_stock_target_price_em(symbol):
    """
    获取美股和港股的目标价格:https://www.ushknews.com/report.html
    symbol="us"; choice of {"us", "hk"}
    :return: 美股和港股的目标价格
    """
    df = ak.stock_price_js(symbol=symbol)
    return df


# 80. A股个股指标
def get_stock_indicator_lg(symbol):
    """
    获取A股个股指标
    symbol=="000001"; 参见 ak.stock_a_indicator_lg(symbol="all") 获取股票代码
    :return: A股个股指标
    """
    df = ak.stock_a_indicator_lg(symbol=symbol)
    return df

# 81. A股股息率
def get_stock_dividend_rate_lg(symbol):
    """
    获取A股股息率
    symbol="上证A股"; choice of {"上证A股", "深证A股", "创业板", "科创板"}
    :return: A股股息率
    """
    df = ak.stock_a_gxl_lg(symbol=symbol)
    return df

# 82. 恒生指数股息率
def get_stock_hk_dividend_rate_lg():
    """
    :return:
    """
    df = ak.stock_hk_gxl_lg()
    return df

# 83. 大盘拥挤度
def get_stock_market_crowding_lg():
    """
    获取大盘拥挤度
    :return: 大盘拥挤度
    """
    df = ak.stock_a_congestion_lg()
    return df

# 84. 股债利差
def get_stock_bond_spread_lg():
    """
    获取股债利差
    :return: 股债利差
    """
    df = ak.stock_ebs_lg()
    return df

# 85. 巴菲特指标
def get_stock_baft_indicator_lg():
    """
    获取巴菲特指标
    :return: 巴菲特指标
    日期	object	交易日
    收盘价	float64	-
    总市值	float64	A股收盘价*已发行股票总股本（A股+B股+H股）
    GDP	float64	上年度国内生产总值（例如：2019年，则取2018年GDP）
    近十年分位数	float64	当前"总市值/GDP"在历史数据上的分位数
    总历史分位数	float64	当前"总市值/GDP"在历史数据上的分位数


    """
    df = ak.stock_buffett_index_lg()
    return df

# 86. A股等权重与中位数市盈率
def get_stock_weighted_median_pe_lg():
    """
    获取A股等权重与中位数市盈率
    :return: A股等权重与中位数市盈率
    date	object	日期
    middlePETTM	float64	全A股滚动市盈率(TTM)中位数
    averagePETTM	float64	全A股滚动市盈率(TTM)等权平均
    middlePELYR	float64	全A股静态市盈率(LYR)中位数
    averagePELYR	float64	全A股静态市盈率(LYR)等权平均
    quantileInAllHistoryMiddlePeTtm	float64	当前"TTM(滚动市盈率)中位数"在历史数据上的分位数
    quantileInRecent10YearsMiddlePeTtm	float64	当前"TTM(滚动市盈率)中位数"在最近10年数据上的分位数
    quantileInAllHistoryAveragePeTtm	float64	当前"TTM(滚动市盈率)等权平均"在历史数据上的分位数
    quantileInRecent10YearsAveragePeTtm	float64	当前"TTM(滚动市盈率)等权平均"在在最近10年数据上的分位数
    quantileInAllHistoryMiddlePeLyr	float64	当前"LYR(静态市盈率)中位数"在历史数据上的分位数
    quantileInRecent10YearsMiddlePeLyr	float64	当前"LYR(静态市盈率)中位数"在最近10年数据上的分位数
    quantileInAllHistoryAveragePeLyr	float64	当前"LYR(静态市盈率)等权平均"在历史数据上的分位数
    quantileInRecent10YearsAveragePeLyr	float64	当前"LYR(静态市盈率)等权平均"在最近10年数据上的分位数
    close	float64	沪深300指数
    """
    df = ak.stock_a_ttm_lyr()
    return df

# 87. A股等权重与中位数市净率
def get_stock_weighted_median_pb_lg():
    """
    获取A股等权重与中位数市净率
    :return: A股等权重与中位数市净率
    date	object	日期
    middlePB	float64	全部A股市净率中位数
    equalWeightAveragePB	float64	全部A股市净率等权平均
    close	float64	上证指数
    quantileInAllHistoryMiddlePB	float64	当前市净率中位数在历史数据上的分位数
    quantileInRecent10YearsMiddlePB	float64	当前市净率中位数在最近10年数据上的分位数
    quantileInAllHistoryEqualWeightAveragePB	float64	当前市净率等权平均在历史数据上的分位数
    quantileInRecent10YearsEqualWeightAveragePB	float64	当前市净率等权平均在最近10年数据上的分位数
    """
    df = ak.stock_a_all_pb()
    return df


# 88. A股主板市盈率
def get_stock_mainboard_pe_lg(symbol):
    """
    获取A股主板市盈率
    symbol="上证"; choice of {"上证", "深证", "创业板", "科创版"}
    :return: A股主板市盈率
    """
    df = ak.stock_market_pe_lg(symbol=symbol)
    return df

# 89. A股指数市盈率
def get_stock_index_pe_lg(symbol):
    """
    获取A股指数市盈率
    symbol=symbol="上证50"; choice of {"上证50", "沪深300", "上证380", "创业板50", "中证500", "上证180", "深证红利", "深证100", "中证1000", "上证红利", "中证100", "中证800"}
    :return: A股指数市盈率
    """
    df = ak.stock_index_pe_lg(symbol=symbol)
    return df

# 90. 主板市净率
def get_stock_mainboard_pb_lg(symbol):
    """
    获取主板市净率
    symbol="上证"; choice of {"上证", "深证", "创业板", "科创版"}
    :return: 主板市净率
    """
    df = ak.stock_market_pb_lg(symbol=symbol)
    return df

# 91. 指数市净率
def get_stock_index_pb_lg(symbol):
    """
    获取指数市净率
    symbol="上证50"; choice of {"上证50", "沪深300", "上证380", "创业板50", "中证500", "上证180", "深证红利", "深证100", "中证1000", "上证红利", "中证100", "中证800"}
    :return: 指数市净率
    """
    df = ak.stock_index_pb_lg(symbol=symbol)
    return df


# 92. A股估值指标
def get_stock_valuation_baidu(symbol, indicator, period):
    """

    symbol	str	symbol="002044"; A 股代码
    indicator	str	indicator="总市值"; choice of {"总市值", "市盈率(TTM)", "市盈率(静)", "市净率", "市现率"}
    period	str	period="近一年"; choice of {"近一年", "近三年", "近五年", "近十年", "全部"}
    :return:
    """
    df = ak.stock_zh_valuation_baidu(symbol=symbol, indicator=indicator, period=period)
    return df

# 93. 个股估值指标
def get_stock_valuation_em(symbol):
    """
    symbol    str    symbol="002044"; A 股代码
    :return:
    """
    df = ak.stock_value_em(symbol=symbol)
    return df

# 94. 百度情绪指标，股民投票
def get_stock_baidu_trend(symbol, indicator):
    """
     symbol="002044"; A 股代码或指数代码
     indicator= "指数"; choice of {"指数", "股票"}
    :return:
    """
    df = ak.stock_zh_vote_baidu(symbol=symbol, indicator=indicator)
    return df

# 95. 港股个股指标
def get_stock_hk_indicator_baidu(symbol, indicator, period):
    """
    获取港股个股指标
    symbol="hk01093"
    indicator=indicator="总市值"; choice of {"总市值", "市盈率(TTM)", "市盈率(静)", "市净率", "市现率"}
    period="近一年"; choice of {"近一年", "近三年", "全部"}
    :return: 港股个股指标
    """
    df = ak.stock_hk_valuation_baidu(symbol=symbol, indicator=indicator, period=period)
    return df



# 96. A股创新高和新低的股票数量
def get_stock_new_high_low(symbol):
    """
    获取A股创新高和新低的股票数量
    :param symbol:="all"; {"all": "全部A股", "sz50": "上证50", "hs300": "沪深300", "zz500": "中证500"}
    :return:
    """
    df = ak.stock_a_high_low_statistics(symbol=symbol)
    return df

# 97. A股破净值统计
def get_stock_below_net_statistics(symbol):
    """
    获取A股破净值统计
    :param symbol="全部A股"; choice of {"全部A股", "沪深300", "上证50", "中证500"}
    date	object	交易日
    below_net_asset	float64	破净股家数
    total_company	float64	总公司数
    below_net_asset_ratio	float64	破净股比率
    :return:
    """
    df = ak.stock_a_below_net_asset_statistics(symbol=symbol)
    return df

# 98. 基金持股明细
def get_fund_hold_detail(symbol, date):
    """
    获取基金持股明细
    symbol="000001"; 基金代码
    date="20200630"; 财报发布日期, xxxx-03-31, xxxx-06-30, xxxx-09-30, xxxx-12-31
    :return:
    """
    df = ak.stock_report_fund_hold_detail(symbol=symbol, date=date)
    return df


# 99. 融资融券名单
def get_stock_margin_ratio(date):
    """
    获取融资融券名单
    date="20200630" 指定交易日
    :return:
    """
    df = ak.stock_margin_ratio_pa(date=date)
    return df

# 100. 两融账户信息
def get_stock_margin_account_info():
    """
    获取两融账户信息
    :return:
    """
    df = ak.stock_margin_account_info()
    return df

# 101. 上交所两融汇总
def get_stock_margin_summary_sh(start_date, end_date):
    """
    获取上交所两融汇总
    start_date="20200630"; 开始日期
    end_date="20200630"; 结束日期
    :return:
    """
    df = ak.stock_margin_sse(start_date=start_date, end_date=end_date)
    return df

# 102. 上交所两融明细
def get_stock_margin_detail_sh(date):
    """
    获取上交所两融明细
    date="20200630"
    :return:
    """
    df = ak.stock_margin_detail_sse(date=date)
    return df

# 103. 深交所两融汇总
def get_stock_margin_summary_sz(date):
    """
    获取深交所两融汇总
    date="20200630";
    :return:
    """
    df = ak.stock_margin_szse(date=date)
    return df

# 104. 深交所两融明细
def get_stock_margin_detail_sz(date):
    """
    获取深交所两融明细
    date="20200630";
    :return:
    """
    df = ak.stock_margin_detail_szse(date=date)
    return df

# 105。 同花顺行业列表
def get_stock_industry_list_ths():
    """
    获取同花顺行业列表
    :return:
    """
    df = ak.stock_board_industry_summary_ths()
    return df

# 106. 同花顺指数数据
def get_stock_index_ths(symbol, start_date, end_date):
    """
    获取同花顺指数数据
    symbol="元件"; 可以通过调用 get_stock_industry_list_ths 查看同花顺的所有行业名称
    start_date="20200630"; 开始日期
    end_date="20200630"; 结束日期
    :return:
    """
    df = ak.stock_board_industry_index_ths(symbol=symbol, start_date=start_date, end_date=end_date)
    return df


# 107. 雪球讨论热度最高个股
def get_stock_hot_tweet_xq(symbol):
    """
    获取雪球讨论热度最高个股
    symbol="最热门"; choice of {"本周新增", "最热门"}
    :return:
    """
    df = ak.stock_hot_tweet_xq(symbol=symbol)
    return df

# 108. 雪球交易排行榜
def get_stock_trade_rank_xq(symbol):
    """
    获取雪球交易排行榜
    symbol="最热门"; choice of {"本周新增", "最热门"}
    :return:
    """
    df = ak.stock_hot_deal_xq(symbol=symbol)
    return df

# 109. 股票热度-东财
def get_stock_hot_rank_em(symbol):
    """
    获取股票热度-东财
    :return:
    """
    df = ak.stock_hot_rank_em()
    return df

# 110. 东财个股飙升榜
def get_stock_rising_rank_em(symbol):
    """
    获取东财个股飙升榜
    :return:
    """
    df = ak.stock_hot_up_em()
    return df
# 111. 港股人气榜-东财
def get_stock_hk_hot_rank_em():
    """
    获取港股人气榜-东财
    :return:
    """
    df = ak.stock_hk_hot_rank_em()
    return df

# 112. 相关股票
def get_stock_related_em(symbol):
    """
    获取相关股票
    symbol="SZ000665";
    :return:
    """
    df = ak.stock_hot_rank_relate_em(symbol=symbol)
    return df

# 113. 昨天涨停股池
def get_stock_yesterday_limit_em(date):
    """
    获取昨天涨停股池
    date="20200630";指定日期的前一天
    :return:
    """
    df = ak.stock_zt_pool_previous_em(date=date)
    return df

# 114. 强势股
def get_stock_strong_em(date):
    """

    :param date:
    :return:
    """
    df =  ak.stock_zt_pool_strong_em(date=date)
    return  df

# 跌停股池
def get_stock_down_limit_em(date):
    """
    date: '20241011'
    :return:
    """
    df = ak.stock_zt_pool_dtgc_em(date=date)
    return df

# 赚钱效应
def get_market_activity_lg():
    """

    :return:
    """
    df = ak.stock_market_activity_legu()
    return df





# if __name__ == '__main__':
    # print(get_stock_info('SH601127'))
    # print(get_stock_quote('000001'))
    # print(get_stock_realtime_quotes())
    # print(get_stock_sh_realtime_quotes())
    # print(get_stock_sz_realtime_quotes())
    # print(get_stock_bj_realtime_quotes())
    # print(get_stock_new_realtime_quotes())
    # print(get_stock_cyb_realtime_quotes())
    # print(get_stock_kcb_realtime_quotes())
    # print(get_stock_xq_realtime_quotes(symbol='SH600000'))
    # print(get_stock_history_em(symbol='603777', period='daily', start_date='20150101', end_date='20250729'))
    # print(get_stock_history_sina(symbol='sh600000', start_date='20150101', end_date='20250729', adjust='qfq'))
    # print(get_stock_history_tencent(symbol='sh600000', start_date='20150101', end_date='20250729', adjust='qfq'))
    # print(get_stock_minute_sina(symbol='sh600000', period='1', adjust='qfq'))
    # print(get_stock_minute_em(symbol='000001', start_date='2025-07-01 09:32:00', end_date='2225-07-29 09:32:00', period='1', adjust='qfq'))
    # print(get_stock_intraday_em(symbol='000001'))
    # print(get_stock_intraday_sina(symbol='sh600000', date='20250729'))
    # print(get_stock_pre_min_em(symbol='000001', start_time='09:00:00', end_time='15:40:00'))
    # print(get_stock_tick_tencent(symbol='sh600000'))
    # print(get_stock_new_stock_sina())
    # print(get_stock_news_em(date='20250729'))
    # print(get_stock_new_stock_em())
    # print(get_stock_kcb_realtime_quotes_sina())
    # print(get_stock_kcb_history_sina(symbol='sh688001', adjust='hfq'))
    # print(get_stock_kcb_report_em(from_page=1, to_page=10))
    # print(get_ah_realtime_spot_em())
    # print(get_ah_history_tencent(symbol='02318', start_year='2000', end_year='2019', adjust='hfq'))
    # print(get_stock_ah_name_tencent())
    # print(get_stock_us_realtime_quotes())
    # print(get_stock_us_realtime_quotes_sina())
    # print(get_stock_us_history(symbol='106.TTE', period='daily', start_date='20150101', end_date='20250729', adjust='hfq'))
    # print(get_stock_hk_realtime_quotes())
    # print(get_stock_hk_main_realtime_quotes())
    # print(get_stock_hk_minute_em(symbol='00700', period='1', start_date='2025-07-01 09:32:00', end_date='2025-07-29 09:32:00', adjust=''))
    # print(get_stock_hk_history_em(symbol='00700', period='daily', start_date='20150101', end_date='20250729', adjust=''))
    # print(get_stock_hk_famous_spot_em())
    # print(get_stock_us_famous_spot_em())
    # print(get_stock_jgdy_em(date='20250722'))
    # print(get_stock_pledge_em())
    # print(get_stock_pledge_ratio_em(date='20250725'))
    # print(get_stock_pledge_detail_em())
    # print(get_stock_pledge_company_em())
    # print(get_stock_pledge_bank_em())
    # print(get_industry_pledge_ratio_em())
    # print(get_stock_account_month_em())
    # print(get_stock_analyst_index_em(year='2025')['分析师ID'])
    # print(get_stock_analyst_detail_em(analyst_id='11000249533', indicator='最新跟踪成分股'))
    # print(get_stock_comment_hot_em())
    # print(get_stock_comment_hot_detail_em(symbol='600000'))
    # print(get_stock_user_attention_em(symbol='600000'))
    # print(get_stock_hsgt_em())
    # print(get_stock_hsgt_history_em(symbol='北向资金'))
    # print(get_stock_performance_em(date='20250630'))
    # print(get_stock_performance_fast_em(date='20250630'))
    # print(get_stock_performance_forecast_em(date='20250630'))
    # print(get_stock_balance_sheet_em(date='20250630'))
    # print(get_stock_balance_sheet_bj_em(date='20250630'))
    # print(get_stock_income_statement_em(date='20250630'))
    # print(get_stock_cash_flow_em(date='20250630'))
    # print(get_stock_shareholder_em(symbol='股东增持'))
    # print(get_stock_dividend_em(date='20250630'))
    # print(get_stock_dividend_detail_em(symbol='600000'))
    # print(get_stock_fund_flow_em(symbol='即时'))
    # print(get_stock_concept_fund_flow_em(symbol='即时'))
    # print(get_stock_industry_fund_flow_em(symbol='即时'))
    # print(get_stock_big_order_em())
    # print(get_stock_fund_flow_detail_em(symbol='600000', market='sh'))
    # print(get_stock_fund_flow_rank_em(indicator='今日'))
    # print(get_sector_fund_flow_rank(indicator='今日', sector_type='行业资金流'))
    # print(get_stock_market_fund_flow_em())
    # print(get_stock_main_fund_flow_rank_em(symbol='全部股票'))
    # print(get_stock_capital_distribution_em(symbol='600000', adjust='hfq'))
    # print(get_stock_shareholder_num_em(symbol='20250630'))
    # print(get_stock_list_em())
    # print(get_stock_list_em(symbol='sh'))
    # print(get_stock_list_em(symbol='sz'))
    # print(get_stock_list_em(symbol='bj'))
    # print(get_stock_list_em(symbol='all'))
    # print(get_stock_target_price_em(symbol='us'))
    # print(get_stock_target_price_em(symbol='hk'))
    # print(get_stock_indicator_lg(symbol='000001'))
    # print(get_stock_dividend_rate_lg(symbol='上证A股'))
    # print(get_stock_hk_dividend_rate_lg())
    # print(get_stock_market_crowding_lg())
    # print(get_stock_bond_spread_lg())
    # print(get_stock_baft_indicator_lg())
    # print(get_stock_baft_indicator_lg())
    # print(get_stock_weighted_median_pe_lg())
    # print(get_stock_weighted_median_pb_lg())
    # print(get_stock_mainboard_pe_lg(symbol='上证'))
    # print(get_stock_index_pe_lg(symbol='上证50'))
    # print(get_stock_mainboard_pb_lg(symbol='上证'))
    # print(get_stock_index_pb_lg(symbol='上证50'))
    # print(get_stock_valuation_baidu(symbol='002044', indicator='总市值', period='近一年'))
    # print(get_stock_valuation_em(symbol='002044'))
    # print(get_stock_baidu_trend(symbol='000001', indicator='指数'))
    # print(get_stock_hk_indicator_baidu(symbol='06969', indicator='市盈率(TTM)', period='近一年'))
    # print(get_stock_new_high_low(symbol='all'))
    # print(get_stock_below_net_statistics(symbol='全部A股'))
    # print(get_fund_hold_detail(symbol='005827', date='20250630'))
    # print(get_stock_margin_ratio(date='20250729'))
    # print(get_stock_margin_account_info())
    # print(get_stock_margin_summary_sh(start_date='20250701', end_date='20250729'))
    # print(get_stock_margin_detail_sh(date='20250729'))
    # print(get_stock_margin_summary_sz(date='20250729'))
    # print(get_stock_margin_detail_sz(date='20250729'))
    # print(get_stock_hot_tweet_xq(symbol='最热门'))
    print(get_stock_trade_rank_xq(symbol='最热门'))