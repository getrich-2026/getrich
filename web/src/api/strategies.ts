import apiClient from './client'
import type { ApiResponse } from '@/types/common'
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

// 获取策略列表
export const getStrategyList = (params?: StrategyListParams) => {
  return apiClient.get<ApiResponse<StrategyListData>>(
    '/strategies',
    { params }
  ) as unknown as Promise<ApiResponse<StrategyListData>>
}

// 获取策略分类列表
export const getStrategyCategories = () => {
  return apiClient.get<ApiResponse<GetCategoriesResponse>>('/strategies/categories')
}

// 获取策略详情
export const getStrategyDetail = (strategyId: string) => {
  return apiClient.get<ApiResponse<StrategyDetail>>(`/strategies/${strategyId}`)
}

// 获取策略净值曲线
export const getEquityCurve = (strategyId: string, params?: EquityCurveParams) => {
  return apiClient.get<ApiResponse<EquityCurveData>>(`/strategies/${strategyId}/equity-curve`, { params })
}

// 获取月度收益矩阵
export const getMonthlyReturns = (strategyId: string) => {
  return apiClient.get<ApiResponse<MonthlyReturnsData>>(`/strategies/${strategyId}/monthly-returns`)
}

// 获取策略回测报告
export const getBacktestReport = (strategyId: string) => {
  return apiClient.get<ApiResponse<BacktestReportData>>(`/strategies/${strategyId}/backtest-report`)
}

// 获取策略历史交易记录
export const getStrategyTrades = (strategyId: string, params?: TradeListParams) => {
  return apiClient.get<ApiResponse<TradeListData>>(`/strategies/${strategyId}/trades`, { params })
}

// 获取策略历史信号列表
export const getStrategySignals = (strategyId: string, params?: SignalListParams) => {
  return apiClient.get<ApiResponse<SignalListData>>(`/strategies/${strategyId}/signals`, { params })
}
