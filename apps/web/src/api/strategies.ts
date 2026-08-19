import { http } from './client'
import type {
  StrategyListParams,
  StrategyListData,
  GetCategoriesResponse,
  StrategyDetail,
  EquityCurveParams,
  EquityCurveData,
  MonthlyReturnsData,
  BacktestReportData,
  TradeListParams,
  TradeListData,
  SignalListParams,
  SignalListData,
} from '@/types/strategy'

// 本模块的函数直接返回后端的 data（信封由 client.ts 的拦截器剥掉），
// 不做任何面向视图的形状转换 —— 那属于组件的职责，放这里会让同一个接口
// 出现多份互相不兼容的返回类型。

// 获取策略列表
export const getStrategyList = (params?: StrategyListParams) =>
  http.get<StrategyListData>('/strategies', { params })

// 获取策略分类列表
export const getStrategyCategories = () =>
  http.get<GetCategoriesResponse>('/strategies/categories')

// 获取策略详情
export const getStrategyDetail = (strategyId: string) =>
  http.get<StrategyDetail>(`/strategies/${strategyId}`)

// 获取策略净值曲线
export const getEquityCurve = (strategyId: string, params?: EquityCurveParams) =>
  http.get<EquityCurveData>(`/strategies/${strategyId}/equity-curve`, { params })

// 获取月度收益矩阵
export const getMonthlyReturns = (strategyId: string) =>
  http.get<MonthlyReturnsData>(`/strategies/${strategyId}/monthly-returns`)

// 获取策略回测报告
export const getBacktestReport = (strategyId: string) =>
  http.get<BacktestReportData>(`/strategies/${strategyId}/backtest-report`)

// 获取策略历史交易记录
export const getStrategyTrades = (strategyId: string, params?: TradeListParams) =>
  http.get<TradeListData>(`/strategies/${strategyId}/trades`, { params })

// 获取策略历史信号列表
export const getStrategySignals = (strategyId: string, params?: SignalListParams) =>
  http.get<SignalListData>(`/strategies/${strategyId}/signals`, { params })
