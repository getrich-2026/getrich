# Author: <QiuZiHua>
# Date: 2025-10-26
# Description: 更新历史数据基础类
# insight 需要的python版本是3.7的
from multiprocessing.connection import default_family
from platform import python_version

import pandas as pd
import numpy as np
from abc import ABC, abstractmethod
from datetime import datetime
import os

# 尝试导入第三方库，如果不可用，则在运行的时处理异常
# 尝试导入 insight
try:
    from insight_python.com.insight import common
    from insight_python.com.insight.playback import *
    from insight_python.com.insight.query import *
    from insight_python.com.insight.market_service import market_service
except ImportError:
    print("无法导入第三方库，请检查是否安装了insight_python")
# 尝试导入同花顺
try:
    from iFinDPy import *
except ImportError:
    print("无法导入同花顺库，请检查是否安装了iFinDPy")

# 数据源抽象基类
class DataAPI(ABC):
    """
    数据源抽象基类，定义所有数据获取方法的接口
    """
    @abstractmethod
    def login(self):
        """登录数据API"""
        pass
    @abstractmethod
    def GetTradeDayList(self, start_date, end_date):
        """获取交易日列表
        Args:
            start_date(str): 开始日期，格式 'YYYY-MM-DD'
            end_date(str): 结束日期，格式 'YYYY-MM-DD'

        Returns:
            list：交易日列表，每个元素为日期字符串
        """
        pass
    @abstractmethod
    def GetOptionBasicInfo(self, undcode=None):
        """获取某个标的期权合约要素表
        Args:
            undcode(str): 标的代码
        Returns:
            DF: 包含期权基本信息的DF
        """
        pass
    @abstractmethod
    def GetOptionTradingContract(self, date=None, undcode=None):
        """
        获取合约信息
        :param date: 指定交易日 YYYY-MM-DD
        :param undcode: 标的代码
        :return: 该品种所有的交易合约
        """
        pass
    @abstractmethod
    def GetStockMarketQuote(self, date=None):
        """
        获取某个交易日的所有股票行情数据
        :param date: 交易日 YYYY-MM-DD
        :return: df
        """
        pass
    @abstractmethod
    def GetFuturesMarketQuote(self, date=None):
        """
        获取date交易日股指期货的行情数据
        :param date: 交易日 YYYY-MM-DD
        :param Undcode: 标的代码
        :return:DF
        """
        pass
    @abstractmethod
    def GetOptionMarketQuote(self, exchange=None, date=None, undcode=None, undname=None):
        """
        获取date交易日，undecode期权行情数据
        :param date: 交易日 YYYY-MM-DD
        :param Undcode: 标的代码
        :return: DF
        """
        pass
    @abstractmethod
    def GetETFMarketQuote(self, start_date=None, end_date=None, etfcode=None):
        """
        获取从start_date到end_date的etfcode的行情数据
        :param start_date: 开始日期 YYYY-MM-DD
        :param end_date: 结束日期 YYYY-MM-DD
        :param etfcode: etf代码
        :return: DF
        """
        pass
    @abstractmethod
    def GetFundDailyInfo(self):
        """获取全市场基金当天的开盘的信息表"""
        pass
    @abstractmethod
    def GetFundMarketQuote(self, start_date=None, end_date=None, fundcode=None):
        """
        获取基金净值数据
        :param start_date: 开始日期 YYYY-MM-DD
        :param end_date: 结束日期 YYYY-MM-DD
        :param fundcode: 基金代码
        :return: DF
        """
        pass
    @abstractmethod
    def GetIndexDailyInfo(self):
        """获取当天所有指数列表"""
        pass
    @abstractmethod
    def GetIndexMarketQuote(self, start_date=None, end_date=None, indexcode=None):
        """
        获取指数行情数据
        :param start_date: 开始日期 YYYY-MM-DD
        :param end_date: 结束日期 YYYY-MM-DD
        :param indexcode: 指数代码
        :return: DF
        """
        pass
    @abstractmethod
    def GetRateMarketQuote(self):
        """
        获取无风险利率的数据
        :return: DF
        """
        pass
    @abstractmethod
    def GetCbondInfo(self, date=None):
        """
        获取交易日date所有的可转债信息
        :param date: 交易日期 YYYY-MM-DD
        :return: DF
        """
        pass
    @abstractmethod
    def GetCbondMarketQuote(self, start_date=None, end_date=None, cbondcode=None):
        """
        获取可转债cbondcode的行情数据
        :param start_date:开始日期 YYYY-MM-DD
        :param end_date: 结束日期 YYYY-MM-DD
        :param cbondcode: 可转债代码
        :return: DF
        """
        pass
    @abstractmethod
    def GetComFuturesMarketQuote(self, date=None, futcode=None):
        """获取商品期货的行情数据
        date：交易日 YYYY-MM-DD
        futcode：期货代码
        """
        pass



# 华泰Insight数据API
class InsightDataAPI(DataAPI):
    """Insight 数据源实现类"""
    def __init__(self):
        self.market_service = market_service

    def login(self):
        """登录Insight数据源"""
        self.market_service = self.market_service
        user = 'MDIL1_00338'
        password = 'Xyzh@230ehfy6'
        result = common.login(self.market_service, user, password)
        print(result)

    def GetTradeDayList(self, start_date, end_date):
        """从Insight获取交易日列表"""
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        data = get_trading_days(exchange='XSHE', trading_day=[start_dt, end_dt])
        data = pd.DataFrame(data=data[1])
        data = data.sort_values(by='TradingDay', ascending=True)
        data = data.rename(columns={'TradingDay': '交易日'})
        data['交易日'] = [pd.to_datetime(date).strftime('%Y-%m-%d') for date in data['交易日']]
        data['数据源'] = 'Insight'
        return data

    def GetOptionBasicInfo(self, undcode=None):
        """从Insight获取合约信息(暂未实现,返回None)
        """
        print('暂不支持从insight获取期权合约要素')
        return None
    def GetStockMarketQuote(self, date=None):
        """从Insight获取股票数据"""
        start_date = datetime.strptime(date, '%Y-%m-%d')
        end_date = datetime.strptime(date, '%Y-%m-%d')
        df = get_daily_basic(trading_day=[start_date, end_date])
        df = df.rename(columns={
            'htsc_code': '股票代码',
            'name': '股票简称',
            'exchange': '交易所',
            'trading_day': '交易日期',
            'trading_state': '交易状态',
            'prev_close': '前收盘价',
            'open': '开盘价',
            'high': '最高价',
            'low': '最低价',
            'close': '收盘价',
            'backward_adjusted_closing_price': '后复权收盘价',
            'volume': '成交量',
            'value': '成交额',
            'turnover_deals': '成交笔数',
            'day_change': '涨跌',
            'turnover_rate': '换手率(%)',
            'amplitude': '振幅(%)',
            'avg_price': '当日均价',
            'avg_vol_per_deal': '平均每笔成交量',
            'avg_value_per_deal': '平均每笔成交金额',
            'floating_market_val': '流通市值(万元)',
            'total_market_val': '发行总市值(元)'
        })
        df = df[['股票代码', '股票简称', '交易所', '交易日期', '交易状态', '前收盘价','开盘价','最高价','最低价','收盘价','成交量','成交额','换手率(%)','振幅(%)']]
        df['数据源'] = 'Insight'
        return df

    def GetETFMarketQuote(self, start_date=None, end_date=None, etfcode=None):
        """从Insight获取ETF数据"""
        time_start = datetime.strptime(start_date + " 09:00:00", '%Y-%m-%d %H:%M:%S')
        time_end = datetime.strptime(end_date + " 16:00:00", '%Y-%m-%d %H:%M:%S')
        df = get_kline(htsc_code=etfcode, time=[time_start, time_end], frequency='daily', fq='none')
        df['time'] = [pd.to_datetime(date).strftime('%Y-%m-%d') for date in df['time']]
        df = df[['htsc_code', 'time', 'open', 'high', 'low', 'close', 'volume', 'num_trades', 'value']]
        df = df.rename(columns={
            'htsc_code': 'ETF代码',
            'time': '交易日期',
            'open': '开盘价',
            'high': '最高价',
            'low': '最低价',
            'close': '收盘价',
            'volume': '成交量',
            'num_trades': '成交笔数',
            'value': '成交额'
        })
        df = [['ETF代码', '交易日期', '开盘价', '最高价', '最低价', '收盘价', '成交量', '成交额']]
        df['数据源'] = 'Insight'
        return df

    def GetFundDailyInfo(self):
        """从Insight获取基金信息"""
        security_type = 'fund'
        exchange = ['XSHG', 'XSHE']
        today = False
        df = get_all_basic_info(security_type=security_type, exchange=exchange, today=today)
        df = df[['htsc_code', 'name', 'listing_date', 'prev_close']]
        df = df.rename(columns={
            'htsc_code': '基金代码',
            'name': '基金简称',
            'listing_date': '上市日期',
            'prev_close': '前收盘价'
        })
        df['数据源'] = 'Insight'
        return df
    def GetIndexDailyInfo(self):
        """从Insight获取指数信息。"""
        security_type = 'index'
        exchange = ['XSHG', 'XSHE']
        today = False
        df = get_all_basic_info(security_type=security_type, exchange=exchange, today=today)
        df = df[['htsc_code', 'name', 'time', 'prev_close']]
        df = df.rename(columns={
            'htsc_code': '指数代码',
            'name': '指数简称',
            'time': '上市日期',
            'prev_close': '前收盘价'
        })
        df['数据源'] = 'Insight'
        return df

    def GetIndexMarketQuote(self, start_date=None, end_date=None, indexcode=None):
        """从Insight获取指数行情数据"""
        time_start = datetime.strptime(start_date + " 09:00:00", '%Y-%m-%d %H:%M:%S')
        time_end = datetime.strptime(end_date + " 23:00:00", '%Y-%m-%d %H:%M:%S')
        df = get_kline(htsc_code=indexcode, time=[time_start, time_end], frequency='daily', fq='none')
        df['time'] = [pd.to_datetime(date).strftime('%Y-%m-%d') for date in df['time']]
        df = df[['htsc_code', 'time', 'open', 'high', 'low', 'close', 'volume', 'value']]
        df = df.rename(columns={
            'htsc_code': '指数代码',
            'time': '交易日期',
            'open': '开盘价',
            'high': '最高价',
            'low': '最低价',
            'close': '收盘价',
            'volume': '成交量',
            'value': '成交额'
        })
        df=df[['指数代码','交易日期','开盘价','最高价','最低价','收盘价','成交量','成交额']]
        df['数据源'] = 'Insight'
        return df

    def GetRateMarketQuote(self):
        """
        从Insight获取利率数据
        :return:
        """
        codelist = ['204001.SH', '204002.SH', '204003.SH', '204004.SH', '204007.SH',
                   '204014.SH', '204028.SH', '204091.SH', '204182.SH']
        df_pool = pd.DataFrame()
        for code in codelist:
            df = get_repo_price(htsc_code=code)
            df = df.sort_values(by=['trading_day'], ascending=True)
            df = df[['trading_day', 'htsc_code', 'name', 'open_rate', 'close_rate', 'highest_rate', 'lowest_rate']]
            df = df.rename(columns={
                'trading_day': '交易日期',
                'htsc_code': '回购代码',
                'name': '回购简称',
                'open_rate': '开盘利率',
                'close_rate': '收盘利率',
                'highest_rate': '最高利率',
                'lowest_rate': '最低利率'
            })
            df_pool = pd.concat([df_pool, df], ignore_index=True)
        df_pool['交易日期'] = [pd.to_datetime(date).strftime('%Y-%m-%d') for date in df_pool['交易日期']]
        df_pool = df_pool[['交易日期','回购代码','回购简称','开盘利率','收盘利率','最高利率','最低利率']]
        df_pool['数据源']='Insight'
        return df_pool

    def GetCbondInfo(self, date=None):
        """
        从Insight获取可转债表
        :param date:
        :return:
        """
        print('Insight可转债名单数据还没实现')
        return None

    def GetCbondMarketQuote(self, start_date=None, end_date=None, cbondcode=None):
        """从Insight获取可转债行情数据（暂未实现）"""
        print('暂不支持从Insight获取可转债行情数据')
        return None

    def GetComFuturesMarketQuote(self, date=None, futcode=None):
        """从Insight获取商品期货行情数据（暂未实现）"""
        print('暂不支持从Insight获取商品期货行情数据')
        return None

    def GetFundMarketQuote(self, start_date=None, end_date=None, fundcode=None):
        """从Insight获取基金净值数据（暂未实现）"""
        print('暂不支持从Insight获取基金净值数据')
        return None

    def GetFuturesMarketQuote(self, date=None):
        """从Insight获取金融期货数据（暂未实现）"""
        print('暂不支持从Insight获取金融期货数据')
        return None

    def GetOptionMarketQuote(self, exchange=None, date=None, undcode=None, undname=None):
        """从Insight获取期权行情数据（暂未实现）"""
        print('暂不支持从Insight获取期权行情数据')
        return None

    def GetOptionTradingContract(self, date=None, undcode=None):
        """从Insight获取期权合约信息（暂未实现）"""
        print('暂不支持从Insight获取期权合约信息')
        return None


#### 同花顺数据源 #########
class THDataAPI(DataAPI):
    """同花顺数据源实现类"""
    def login(self):
        """登录同花顺数据源"""
        thslogin = THS_iFinDLogin('xyzhsm003', 'zihuaXY2025')
        if thslogin != 0:
            print('同花顺登录失败')
        else:
            print('同花顺登录成功')

    def GetTradeDayList(self, start_date, end_date):
        """从同花顺获取交易日列表"""
        data = THS_Date_Query('212001', 'mode:1,dateType:0,period:D,dateFormat:0', start_date, end_date, 'format:dict')
        data = pd.DataFrame(data.data)
        data = data.rename(columns={'time': '交易日'})
        data['数据源'] = '同花顺'
        return data

    def GetOptionTradingContract(self, date=None, undcode=None):
        """
        从同花顺获取正在交易的期权合约信息
        :param date:
        :param undcode:
        :return:
        """
        data = THS_DR('p02653',
                      f'sdate={date};edate={date};bdid={undcode};hyzt=0',
                      'p02653_f001:Y,p02653_f002:Y,p02653_f008:Y,'
                      'p02653_f011:Y,p02653_f014:Y,p02653_f015:Y,'
                      'p02653_f016:Y,p02653_f005:Y',
                      'format:dataframe')
        data = data.data.rename(columns={
            'p02653_f001': '合约代码',
            'p02653_f002': '合约名称',
            'p02653_f008': '标的代码',
            'p02653_f011': '认购认沽',
            'p02653_f014': '合约乘数',
            'p02653_f015': '行权价格',
            'p02653_f016': '上市日期',
            'p02653_f005': '到期日'
        })
        data['数据源'] = '同花顺'
        return data

    def GetStockMarketQuote(self, date=None):
        """从同花顺获取股票数据"""
        print('从同花顺获取股票数据暂未实现，返回None')
        return None

    def GetComFuturesMarketQuote(self, date=None, futcode=None):
        """从同花顺获取商品期货行情数据"""
        exchangecode = {'212020003':'郑商所','212020004':'大商所', '212020008':'上期所', '212020019':'广期所'}
        df_pool = pd.DataFrame()
        for code in exchangecode.keys():
            exchange_code = code
            exchange_name = exchangecode[code]
            data = THS_DR('p03258',
                          'sdate=' + date + ';edate=' + date +
                          ';jysid=' + exchange_code + ';qhpzid=' + futcode +
                          ';qhhyid=' + futcode + '',
                          'p03258_f001:Y,p03258_f002:Y,p03258_f003:Y,'
                          'p03258_f004:Y,p03258_f005:Y,p03258_f006:Y,'
                          'p03258_f007:Y,p03258_f008:Y,p03258_f009:Y,'
                          'p03258_f010:Y,p03258_f011:Y,p03258_f012:Y,'
                          'p03258_f013:Y,p03258_f014:Y,p03258_f015:Y,'
                          'p03258_f016:Y,p03258_f017:Y', 'format:dataframe')
            if data.errorcode != 0:
                print(data.errorcode)
                print(data.errmsg)
                return None
            else:
                df = data.data.rename(columns={'p03258_f001': '合约代码',
                                               'p03258_f002': '合约名称',
                                               'p03258_f003': '交易日期',
                                               'p03258_f004': '前结算价',
                                               'p03258_f005': '开盘价',
                                               'p03258_f006': '最高价',
                                               'p03258_f007': '最低价',
                                               'p03258_f008': '收盘价',
                                               'p03258_f009': '平均价',
                                               'p03258_f010': '涨跌(收-结)',
                                               'p03258_f011': '涨跌(结-结)',
                                               'p03258_f012': '涨跌幅',
                                               'p03258_f013': '持仓量',
                                               'p03258_f014': '日增仓',
                                               'p03258_f015': '成交量',
                                               'p03258_f016': '成交金额(万元)',
                                               'p03258_f017': '成交金额变化率(%)'})
                df_pool = pd.concat([df_pool, df], ignore_index=True)

        df_pool['数据源'] = '同花顺'
        return df_pool
    def GetFuturesMarketQuote(self, date=None):
        """从同花顺获取金融期货数据"""
        data = THS_DR('p00755','sclx=中金所股指期货;'
                               'date=' + date + '','p00755_f001:Y,'
                                                   'p00755_f002:Y,p00755_f003:Y,'
                                                   'p00755_f004:Y,p00755_f005:Y,'
                                                   'p00755_f006:Y,p00755_f007:Y,'
                                                   'p00755_f008:Y,p00755_f009:Y,'
                                                   'p00755_f014:Y,p00755_f017:Y,'
                                                   'p00755_f020:Y,p00755_f023:Y,'
                                                   'format:dataframe')
        if data.errorcode!= 0:
            print(data.errorcode)
            print(data.errmsg)
            return None
        else:
            df = data.data.rename(columns={'p00755_f001': '合约代码',
                                           'p00755_f002': '合约名称',
                                           'p00755_f003': '交易日期',
                                           'p00755_f004': '前结算价',
                                           'p00755_f005': '前收盘价',
                                           'p00755_f006': '开盘价',
                                           'p00755_f007': '最高价',
                                           'p00755_f008': '最低价',
                                           'p00755_f009': '收盘价',
                                           'p00755_f014': '结算价',
                                           'p00755_f017': '持仓量',
                                           'p00755_f020': '成交量',
                                           'p00755_f023': '成交金额(万元)'
                                           })
            df['数据源'] = '同花顺'
            return df


    def GetOptionMarketQuote(self, exchange=None, date=None, undcode=None, undname=None):
        """
        从同花顺获取期权行情数据
        :param exchange: 上海证券交易所，深圳证券交易所，大连商品交易所，上海期货交易所，大连商品期货交易所，中国金融期货交易所
        :param date: YYYY-MM-DD
        :param undcode:510050.SH ; 510300.SH ; 510500.SH; 588000.SH; 159915.SZ ; 000016.SH； 000300.SH； 000852.SH
        :param undname:50ETF(510050); 300ETF(510300) ; 500ETF(510500); 科创50(588000); 创业板ETF(159915); 上证50指数(000016); 沪深300指数(000300)；中证1000指数(000852)
        :return:
        """
        df = THS_DR('p02834', 'sdate='+ date +';edate='+ date + ';jys=' + exchange +';bdpz='+ undname + ';bdhy='+ undcode + ';qqhy=全部',
               'p02834_f028:Y,p02834_f027:Y,p02834_f001:Y,p02834_f002:Y,p02834_f003:Y,'
                        'p02834_f004:Y,p02834_f005:Y,p02834_f006:Y,p02834_f007:Y,p02834_f008:Y,p02834_f012:Y,'
                        'p02834_f013:Y,p02834_f014:Y,p02834_f015:Y,p02834_f017:Y,p02834_f024:Y,p02834_f026:Y,p02834_f025:Y',
               'format:dataframe')

        if df.errorcode!= 0:
            print(df.errorcode)
            print(df.errmsg)
            return None
        else:
            df = df.data.rename(columns={'p02834_f028': '合约代码',
                                         'p02834_f027': '合约名称',
                                         'p02834_f001': '交易日期',
                                         'p02834_f002': '前结算价',
                                         'p02834_f003': '开盘价',
                                         'p02834_f004': '最高价',
                                         'p02834_f005': '最低价',
                                         'p02834_f006': '收盘价',
                                         'p02834_f007': '结算价',
                                         'p02834_f008': '前收盘价',
                                         'p02834_f012': '成交量',
                                         'p02834_f013': '成交额(万元)',
                                         'p02834_f014': '持仓量',
                                         'p02834_f015': '持仓量变化',
                                         'p02834_f017': '行权价',
                                         'p02834_f024': '到期剩余天数',
                                         'p02834_f026': '到期剩余交易日',
                                         'p02834_f025': '到期日'})
            df['数据源'] = '同花顺'
            return df

    def GetETFMarketQuote(self, start_date=None, end_date=None, etfcode=None):
        print('同花顺ETF数据还没写')
        return None
    def GetFundDailyInfo(self):
        print('同花顺对基金数据还没写')
        return None

    def GetRateMarketQuote(self):
        print('同花顺对回购利率数据还没写好')
        return None

    def GetCbondInfo(self, date=None):
        """从同花顺获取可转债信息（暂未实现）"""
        print('暂不支持从同花顺获取可转债信息')
        return None

    def GetCbondMarketQuote(self, start_date=None, end_date=None, cbondcode=None):
        """从同花顺获取可转债行情数据（暂未实现）"""
        print('暂不支持从同花顺获取可转债行情数据')
        return None

    def GetFundMarketQuote(self, start_date=None, end_date=None, fundcode=None):
        """从同花顺获取基金净值数据（暂未实现）"""
        print('暂不支持从同花顺获取基金净值数据')
        return None

    def GetIndexDailyInfo(self):
        """从同花顺获取指数信息（暂未实现）"""
        print('暂不支持从同花顺获取指数信息')
        return None

    def GetIndexMarketQuote(self, start_date=None, end_date=None, indexcode=None):
        """从同花顺获取指数行情数据（暂未实现）"""
        print('暂不支持从同花顺获取指数行情数据')
        return None

    def GetOptionBasicInfo(self, undcode=None):
        """从同花顺获取期权合约要素（暂未实现）"""
        print('暂不支持从同花顺获取期权合约要素')
        return None









# 切换数据源API和python版本
class DataSourceAPI:
    """数据源选择"""

    @staticmethod
    def create_data_source(source_type):
        """
        :param source_type: str 数据源类型，insight或者tonghuashun
        :return: DataSource 数据源实例
        """
        if source_type.lower() == 'insight':
            return InsightDataAPI()
        elif source_type.lower() == 'tonghuashun':
            return THDataAPI()
        else:
            raise ValueError(f'没有或者还没写这个数据源：{source_type}')


# 金融数据管理器
class DataManager:
    """金融数据管理器, 用于最终的统一数据获取并支持数据源切换"""

    def __init__(self, data_source_type='insight'):
        """初始化金融数据管理器
        Args:
            data_source_type: str 数据源类型，insight或者tonghuashun
        """
        self._data_source = None
        self.switch_data_source(data_source_type)

    def switch_data_source(self, data_source_type):
        """切换数据源
        Args:
            data_source_type: str 数据源类型，insight或者tonghuashun
        """
        api_source = DataSourceAPI()
        self._data_source = api_source.create_data_source(data_source_type)
        if self._data_source is None:
            raise ValueError(f'无效的数据源类型: {data_source_type}')
        self._data_source.login()
        print(f'切换数据源为：{data_source_type}')

    def GetTradeDayList(self, start_date=None, end_date=None):
        """获取交易日列表"""
        if self._data_source is None:
            raise ValueError('数据源未初始化，请先调用 switch_data_source 方法')
        data = self._data_source.GetTradeDayList(start_date, end_date)
        return data




# DataManager(data_source_type='tonghuashun').GetTradeDayList('2025-01-01', '2025-06-01')
































