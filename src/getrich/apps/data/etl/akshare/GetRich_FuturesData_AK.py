# pyright: reportMissingParameterType=false
"""
# -*- coding: utf-8 -*-
从AKShare获取期货数据
Author: QiuZiHua
Date: 2025/07/31
"""

import warnings

import akshare as ak
import pandas as pd

warnings.filterwarnings("ignore")


# 1. 获取期货手续费和保证金
def get_futures_commission(symbol: str) -> pd.DataFrame:
    """
    获取期货手续费和保证金
    symbol = "所有"; choice of {"所有", "上海期货交易所", "大连商品交易所", "郑州商品交易所", "上海国际能源交易中心", "中国金融期货交易所", "广州期货交易所"}
    :return: df
    """
    df: pd.DataFrame = ak.futures_comm_info(symbol=symbol)
    return df


# 2. 获取期货交易日历表
def get_futures_calendar_rule(date: str) -> pd.DataFrame:
    """
    获取期货交易日历表
    date = '20250731'
    :return: df
    """
    try:
        df: pd.DataFrame = ak.futures_rule(date=date)
    except Exception as e:
        print(str(e) + ", 应该这个交易日没有交易日历数据表")
        df = pd.DataFrame()
    return df


# 3. 获取所有期货品种指定日期的基差数据
def get_futures_basis_1(symbol: str) -> pd.DataFrame:
    """
    获取期货2011年以后的基差数据
    symbol = date
    :return: df
    """
    df: pd.DataFrame = ak.futures_spot_price_previous(symbol)
    return df


# 4. 获取指定品种的历史某段时间的基差值
def get_futures_basis_2(symbol: list[str], start_date: str, end_date: str) -> pd.DataFrame:
    """
    获取期货2011年以后的基差数据
    symbol = ["CU", "RB"]
    start_date = '20250731'
    end_date = '20250731'
    :return: df
    """
    df: pd.DataFrame = ak.futures_spot_price_daily(
        start_day=start_date, end_day=end_date, vars_list=symbol
    )  # type: ignore
    return df


# 5. 获取某段时间的会员持仓排名前5名，前10名，前15名，前20名的总和
def get_futures_position_rank_sum(
    symbol: list[str], start_date: str, end_date: str
) -> pd.DataFrame:
    """
    symbol = ["CU", "RB"]
    start_date = '20250731'
    end_date = '20250731'
    :return: df
    """
    df: pd.DataFrame = ak.get_rank_sum_daily(
        vars_list=symbol, start_day=start_date, end_day=end_date
    )
    return df


# 6. 获取某个交易日所有品种的持仓排名榜
def get_futures_position_rank_table(exchangename: str, date: str) -> pd.DataFrame:
    """
    date = '20250731'
    eschangename = 交易所名称：大商所，郑商所，上期所，中金所，广期所
    """
    df: pd.DataFrame = pd.DataFrame()
    if exchangename == "郑商所":
        df = ak.get_rank_table_czce(date=date)  # type: ignore
    elif exchangename == "大商所":
        df = ak.futures_dce_position_rank(date=date)  # type: ignore
    elif exchangename == "上期所":
        df = ak.get_shfe_rank_table(date=date)  # type: ignore
    elif exchangename == "中金所":
        df = ak.get_cffex_rank_table(date=date)  # type: ignore
    elif exchangename == "广期所":
        df = ak.futures_gfex_position_rank(date=date)  # type: ignore
    return df


# 7. 获取某个交易日所有品种的仓单日报
def get_futures_warrant_table(exchangename: str, date: str) -> pd.DataFrame:
    """
    date = '20250731'
    eschangename = 交易所名称：大商所，郑商所，上期所，中金所，广期所
    """
    df: pd.DataFrame = pd.DataFrame()
    if exchangename == "郑商所":
        df = ak.futures_warehouse_receipt_czce(date=date)  # type: ignore
    elif exchangename == "大商所":
        df = ak.futures_warehouse_receipt_dce(date=date)  # type: ignore
    elif exchangename == "上期所":
        df = ak.futures_shfe_warehouse_receipt(date=date)  # type: ignore
    elif exchangename == "广期所":
        df = ak.futures_gfex_warehouse_receipt(date=date)  # type: ignore
    return df


# 8. 指定日期，指定交易所在交易的期货合约信息
def get_futures_contract_info(exchangename: str, date: str | None = None) -> pd.DataFrame:
    """
    date = '20250731'
    eschangename = 交易所名称：大商所，郑商所，上期所，中金所，广期所,上海能源中心
    """
    df: pd.DataFrame = pd.DataFrame()
    if exchangename == "郑商所":
        df = ak.futures_contract_info_czce(date=date)  # type: ignore
    elif exchangename == "大商所":
        df = ak.futures_contract_info_dce()
    elif exchangename == "上期所":
        df = ak.futures_contract_info_shfe(date=date)  # type: ignore
    elif exchangename == "中金所":
        df = ak.futures_contract_info_cffex(date=date)  # type: ignore
    elif exchangename == "广期所":
        df = ak.futures_contract_info_gfex()
    elif exchangename == "上海能源中心":
        df = ak.futures_contract_info_ine(date=date)  # type: ignore
    return df


# 9. 获取内盘期货的实时行情
def get_futures_realtime(subscribe_str: str, market: str, adjust: str) -> pd.DataFrame:
    """
    subscribe_str ='FG2509, AU2510'； 合约代码
    market = market="CF": 商品期货, market="FF": 金融期货
    adjust = adjust='0'; adjust='1': 返回合约、交易所和最小变动单位的实时数据, 返回数据会变慢
    """
    df: pd.DataFrame = ak.futures_zh_spot(symbol=subscribe_str, market=market, adjust=adjust)
    return df


# 10. 获取主力合约的实时行情
def get_futures_main_contract_realtime() -> pd.DataFrame:
    """ """
    dce_text = ak.match_main_contract(symbol="dce")
    czce_text = ak.match_main_contract(symbol="czce")
    shfe_text = ak.match_main_contract(symbol="shfe")
    gfex_text = ak.match_main_contract(symbol="gfex")
    df: pd.DataFrame = ak.futures_zh_spot(
        symbol=",".join([dce_text, czce_text, shfe_text, gfex_text]), market="CF", adjust="0"
    )
    return df


# 11. 订阅中心所所有金融期货主力合约
def get_futures_financial_main_contract() -> pd.DataFrame:
    """ """
    cffex_text = ak.match_main_contract(symbol="cffex")
    df: pd.DataFrame = ak.futures_zh_spot(symbol=cffex_text, market="FF", adjust="0")
    return df


# 12. 获取所有主力合约
def get_futures_all_main_contract() -> dict[str, str]:
    """ """
    dce_text = ak.match_main_contract(symbol="dce")
    czce_text = ak.match_main_contract(symbol="czce")
    shfe_text = ak.match_main_contract(symbol="shfe")
    gfex_text = ak.match_main_contract(symbol="gfex")
    cffex_text = ak.match_main_contract(symbol="cffex")
    data: dict[str, str] = {
        "dce": dce_text,
        "czce": czce_text,
        "shfe": shfe_text,
        "gfex": gfex_text,
        "cffex": cffex_text,
    }
    return data


# 13. 所有品种命名表
def get_futures_all_name() -> pd.DataFrame:
    """ """
    df: pd.DataFrame = ak.futures_symbol_mark()
    return df


# 14. 根据品种获取实时行情数据
def get_futures_realtime_by_name(symbol: str) -> pd.DataFrame:
    """
    symbol = '沪铜',可以通过get_futures_all_name()获取
    symbol	object	合约代码
    exchange	object	交易所
    name	object	合约中文名称
    trade	float64	最新价
    settlement	float64	动态结算
    presettlement	float64	昨日结算
    open	float64	今开
    high	float64	最高
    low	float64	最低
    close	float64	收盘
    bidprice1	float64	买入
    askprice1	float64	卖出
    bidvol1	int64	买量
    askvol1	int64	卖量
    volume	int64	成交量
    position	int64	持仓量
    ticktime	object	时间
    tradedate	object	日期
    preclose	float64	前收盘价
    changepercent	float64	涨跌幅
    bid	float64	-
    ask	float64	-
    prevsettlement	float64	前结算价
    """
    df: pd.DataFrame = ak.futures_zh_realtime(symbol=symbol)
    return df


# 15. 内盘获取分时行情数据
def get_futures_minute(symbol: str, period: str) -> pd.DataFrame:
    """
    symbol = 'FG2509'
    period = '1'  # 1: 1分钟, 5: 5分钟, 15: 15分钟, 30: 30分钟, 60: 60分钟
    datetime	object	-
    open	float64	-
    high	float64	-
    low	float64	-
    close	float64	-
    volume	int64	-
    hold	int64	持仓量
    """
    df: pd.DataFrame = ak.futures_zh_minute_sina(symbol=symbol, period=period)
    return df


# 16. 获取内盘历史行情数据-东财
def get_futures_hist_em(symbol: str, period: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    ymbol="热卷主连"; 具体合约可以通过 get_futures_hist_table_em 获取所有当期能获取数据的合约表
    period = "daily"; choice of {"daily", "weekly", "monthly"}
    start_date = '20250701'
    end_date = '20250731'
    """
    df: pd.DataFrame = ak.futures_hist_em(
        symbol=symbol, period=period, start_date=start_date, end_date=end_date
    )
    return df


# 17. 获取所有当期能获取数据的合约表
def get_futures_hist_table_em() -> pd.DataFrame:
    """ """
    df: pd.DataFrame = ak.futures_hist_table_em()
    return df


# 18. 获取历史行情数据-新浪
def get_futures_hist_sina(symbol: str) -> pd.DataFrame:
    """
    symbol = 'FG2509'
    symbol="RB0"; 具体合约可以通过 get_futures_all_main_contract() 获取或者访问网页
    """
    df: pd.DataFrame = ak.futures_zh_daily_sina(symbol=symbol)
    return df


# 19. 从交易所获取历史行情数据
def get_futures_hist_exchange(start_date: str, end_date: str, market: str) -> pd.DataFrame:
    """
    start_date = '20250701'
    end_date = '20250731'
    market = 'DCE' # choice of  {"CFFEX", "INE", "CZCE", "DCE", "SHFE", "GFEX"}
    symbol	str	合约
    date	str	交易日
    open	float	开盘价
    high	float	最高价
    low	float	最低价
    close	str	收盘价
    volume	str	成交量
    open_interest	str	持仓量
    turnover	float	成交额
    settle	float	结算价
    pre_settle	float	前结算价
    variety	str	品种
    """
    df: pd.DataFrame = ak.get_futures_daily(start_date=start_date, end_date=end_date, market=market)
    return df


# 20.获取外盘品种
def get_futures_foreign_info() -> pd.DataFrame:
    """
    获取外盘的品种名称和代码
    """
    df: pd.DataFrame = ak.futures_hq_subscribe_exchange_symbol()
    return df


# 21. 获取外盘实时行情数据
def get_futures_foreign_realtime(symbol: str) -> pd.DataFrame:
    """
    symbol：‘CT,NID’，通过 get_futures_foreign_info() 获取
    """
    df: pd.DataFrame = ak.futures_foreign_commodity_realtime(symbol=symbol)
    return df


# 22. 获取外盘的实时行情-东财
def get_futures_foreign_realtime_em() -> pd.DataFrame:
    """ """
    df: pd.DataFrame = ak.futures_global_spot_em()
    return df


# 23. 外盘历史行情数据-东财
def get_futures_foreign_hist_em(symbol: str) -> pd.DataFrame:
    """
    symbol="HG00Y"; 品种代码；可以通过 get_futures_realtime_em() 来获取所有可获取历史行情数据的品种代码
    """
    df: pd.DataFrame = ak.futures_global_hist_em(symbol=symbol)
    return df


# 24. 外盘历史行情数据-新浪
def get_futures_foreign_hist_sina(symbol: str) -> pd.DataFrame:
    """
    symbol="ZSD"; 外盘期货的 symbol 可以通过 get_futures_foreign_info() 获取
    """
    df: pd.DataFrame = ak.futures_foreign_hist(symbol=symbol)
    return df


# 25. 获取外盘期货合约详情
def get_futures_foreign_contract_info(symbol: str) -> pd.DataFrame:
    """
    symbol="ZSD"; 外盘期货的 symbol 可以通过 get_futures_foreign_info() 获取
    """
    df: pd.DataFrame = ak.futures_foreign_detail(symbol=symbol)
    return df


# 26. 新加坡交易所期货合约信息
def get_futures_contract_info_xjs(date: str) -> pd.DataFrame:
    """
    date = '20250731'
    DATE	int64	日期
    COM	object	品种代码
    COM_MM	int64	品种到期月份
    COM_YY	int64	品种年份
    OPEN	float64	开盘价
    HIGH	float64	最高价
    LOW	float64	最低价
    CLOSE	float64	收盘价
    SETTLE	float64	结算价
    VOLUME	int64	交易量
    OINT	int64	未平仓合约
    SERIES	object	合约代码
    """
    df: pd.DataFrame = ak.futures_settlement_price_sgx(date=date)
    return df


# 27. 获取期货连续合约数据-新浪
def get_futures_continuous_sina(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    symbol = 'FG0'; 具体合约可以通过 28条 获取或者访问网页；一般是代码+0
    start_date = '20250701'
    end_date = '20250731'
    日期	object	-
    开盘价	int64	-
    最高价	int64	-
    最低价	int64	-
    收盘价	int64	-
    成交量	int64	注意单位
    持仓量	int64	注意单位
    动态结算价	int64
    """
    df: pd.DataFrame = ak.futures_main_sina(symbol=symbol, start_date=start_date, end_date=end_date)
    return df


# 28. 获取期货连续合约数据-新浪
"""
0	V0	dce	PVC连续
1	P0	dce	棕榈油连续
2	B0	dce	豆二连续
3	M0	dce	豆粕连续
4	I0	dce	铁矿石连续
5	JD0	dce	鸡蛋连续
6	L0	dce	塑料连续
7	PP0	dce	聚丙烯连续
8	FB0	dce	纤维板连续
9	BB0	dce	胶合板连续
10	Y0	dce	豆油连续
11	C0	dce	玉米连续
12	A0	dce	豆一连续
13	J0	dce	焦炭连续
14	JM0	dce	焦煤连续
15	CS0	dce	淀粉连续
16	EG0	dce	乙二醇连续
17	RR0	dce	粳米连续
18	EB0	dce	苯乙烯连续
19	PG0	dce	液化石油气连续
20	LH0	dce	生猪连续
21	TA0	czce	PTA连续
22	OI0	czce	菜油连续
23	RS0	czce	菜籽连续
24	RM0	czce	菜粕连续
25	WH0	czce	强麦连续
26	JR0	czce	粳稻连续
27	SR0	czce	白糖连续
28	CF0	czce	棉花连续
29	RI0	czce	早籼稻连续
30	MA0	czce	甲醇连续
31	FG0	czce	玻璃连续
32	LR0	czce	晚籼稻连续
33	SF0	czce	硅铁连续
34	SM0	czce	锰硅连续
35	CY0	czce	棉纱连续
36	AP0	czce	苹果连续
37	CJ0	czce	红枣连续
38	UR0	czce	尿素连续
39	SA0	czce	纯碱连续
40	PF0	czce	短纤连续
41	PK0	czce	花生连续
42	SH0	czce	烧碱连续
43	PX0	czce	对二甲苯连续
44	FU0	shfe	燃料油连续
45	SC0	ine	上海原油连续
46	AL0	shfe	铝连续
47	RU0	shfe	天然橡胶连续
48	ZN0	shfe	沪锌连续
49	CU0	shfe	铜连续
50	AU0	shfe	黄金连续
51	RB0	shfe	螺纹钢连续
52	WR0	shfe	线材连续
53	PB0	shfe	铅连续
54	AG0	shfe	白银连续
55	BU0	shfe	沥青连续
56	HC0	shfe	热轧卷板连续
57	SN0	shfe	锡连续
58	NI0	shfe	镍连续
59	SP0	shfe	纸浆连续
60	NR0	ine	20号胶连续
61	SS0	shfe	不锈钢连续
62	LU0	ine	低硫燃料油连续
63	BC0	ine	国际铜连续
64	AO0	shfe	氧化铝连续
65	BR0	shfe	丁二烯橡胶连续
66	EC0	ine	集运指数欧线期货连续
67	IF0	cffex	沪深300指数期货连续
68	TF0	cffex	5年期国债期货连续
69	IH0	cffex	上证50指数期货连续
70	IC0	cffex	中证500指数期货连续
71	TS0	cffex	2年期国债期货连续
72	IM0	cffex	中证连续指数期货连续
73	SI0	gfex	工业硅连续
74	LC0	gfex	碳酸锂连续
75	PS0	gfex	多晶硅连续
"""


# 29. 期货对应的股票
def get_futures_stock(symbol: str) -> pd.DataFrame:
    """
    symbol = symbol="能源"; choice of {'能源', '化工', '塑料', '纺织', '有色', '钢铁', '建材', '农副'}
    商品名称	object	-
    近5月	float64	注意: 具体的日期
    近4月	float64	注意: 具体的日期
    近3月	float64	注意: 具体的日期
    近2月	float64	注意: 具体的日期
    近1月	float64	注意: 具体的日期
    最新价	float64	-
    近半年涨跌幅	float64	注意单位: %
    生产商	object	注意: 字符串组成
    下游用户	object	注意: 字符串组成
    """
    df: pd.DataFrame = ak.futures_spot_stock(symbol=symbol)
    return df


# 30. 获取COMEX黄金和白银的库存数据
def get_futures_commission_comex(symbol: str) -> pd.DataFrame:
    """
    symbol="黄金"; choice of {"黄金", "白银"}
    :param symbol:
    :return:
    """
    df: pd.DataFrame = ak.futures_comex_inventory(symbol=symbol)
    return df


# 31. 玄田数据-生猪价格
def get_futures_pig_price(symbol: str) -> pd.DataFrame:
    """

    :param symbol:symbol="外三元"; choice of {"外三元", "内三元", "土杂猪"}
    :return:
    """
    df: pd.DataFrame = ak.futures_hog_core(symbol=symbol)
    return df


# 32. 获取成本维度-玉米
def get_futures_pig_cost_dimension(symbol: str) -> pd.DataFrame:
    """
    symbol="玉米"; choice of {"玉米", "豆粕", "二元母猪价格", "仔猪价格"}
    :param symbol:
    :return:
    """
    df: pd.DataFrame = ak.futures_hog_cost(symbol=symbol)
    return df


# 33. 供应维度
def get_futures_pig_supply_dimension(symbol: str) -> pd.DataFrame:
    """
    symbol="玉米"; choice of {"猪肉批发价", "储备冻猪肉", "饲料原料数据", "白条肉", "生猪产能", "育肥猪", "肉类价格指数", "猪粮比价"}
    :param symbol:
    :return:
    """
    df: pd.DataFrame = ak.futures_hog_supply(symbol=symbol)
    return df


# 34. 生猪市场价格指数
def get_futures_pig_price_index() -> pd.DataFrame:
    """
    日期	object	-
    指数	float64	-
    4个月均线	float64	-
    6个月均线	float64	-
    12个月均线	float64	-
    预售均价	float64	注意单位: 元/公斤
    成交均价	float64	注意单位: 元/公斤
    成交均重	int64	注意单位: kg
    """
    df: pd.DataFrame = ak.index_hog_spot_price()
    return df


if __name__ == "__main__":
    # df = get_futures_commission(symbol="所有")
    # print(get_futures_calendar_rule(date='20250731'))
    # print(get_futures_basis_1('20250731'))
    # print(get_futures_basis_2(symbol=["CU", "RB"], start_date='20250701', end_date='20250731'))
    # print(get_futures_position_rank_sum(symbol=["CU", "RB"], start_date='20250701', end_date='20250731'))
    # print(get_futures_position_rank_table('大商所',date='20250731'))
    # print(get_futures_warrant_table('上期所',date='20250731'))
    # print(get_futures_contract_info('大商所',date='20250731'))
    # print(get_futures_realtime(subscribe_str='FG2509, AU2510', market="CF", adjust='0'))
    # print(get_futures_main_contract_realtime())
    # print(get_futures_financial_main_contract())
    # print(get_futures_all_main_contract())
    # print(get_futures_all_name())
    # print(get_futures_realtime_by_name(symbol='沪铜'))
    # print(get_futures_minute(symbol='FG2509', period='1'))
    # print(get_futures_hist_em(symbol="热卷主连", period="daily", start_date='20250701', end_date='20250731'))
    # print(get_futures_hist_table_em())
    # print(get_futures_hist_sina(symbol='FG2509'))
    # print(get_futures_hist_exchange(start_date='20200701', end_date='20200731', market='DCE'))
    # print(get_futures_foreign_info())
    # print(get_futures_foreign_realtime(symbol='CT,NID'))
    # print(get_futures_foreign_realtime_em())
    # print(get_futures_foreign_hist_em(symbol="HG00Y"))
    # print(get_futures_foreign_hist_sina(symbol="FEF"))
    # print(get_futures_foreign_contract_info(symbol="ZSD"))
    # print(get_futures_contract_info_xjs(date='20250731'))

    # print(get_futures_continuous_sina(symbol='FG0', start_date='20200701', end_date='20250731'))
    print(get_futures_stock(symbol="能源"))
