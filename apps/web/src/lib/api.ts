// 后端基址统一由 VITE_API_BASE_URL 提供（值里已含 /v1 前缀），与 src/api/client.ts 一致。
// 不要在源码里硬编码服务器地址 —— 本仓库是公开仓库。
import type { ApiResponse } from '@/types/common'
import type {
  GetCategoriesResponse,
  StrategyListParams,
  StrategyListData,
  StrategyDetail,
  EquityCurveData,
  MonthlyReturnsData,
  BacktestReportData,
  TradeListData,
  SignalListParams,
  SignalListData,
} from '@/types/strategy'
import type { SignalDetail } from '@/types/signal'

const BASE_URL = import.meta.env.VITE_API_BASE_URL

// 统一请求封装，自动校验 code 并抛错
async function request<T>(url: string): Promise<T> {
  const res = await fetch(BASE_URL + url)
  const json = (await res.json()) as ApiResponse<T>
  if (json.code !== 0) throw new Error(json.message)
  return json.data
}

// URLSearchParams 只接受 string 值，这里把 number / boolean 统一转成字符串，
// 并剔除 null / undefined —— 直接把参数对象强转成 Record<string,string> 会在
// 传 number 时骗过类型检查。
function toQuery<T extends object>(params?: T): string {
  const entries = Object.entries(params ?? {}) as [string, unknown][]
  const pairs: string[][] = entries
    .filter(([, v]) => v != null)
    .map(([k, v]) => [k, String(v)])
  const query = new URLSearchParams(pairs).toString()
  return query ? `?${query}` : ''
}

// 净值曲线经过转换后喂给 ECharts，形状与后端原始响应不同
export interface EquityCurveSeries {
  dates: string[]
  nav: number[]
  benchmark: number[]
  drawdown: number[]
}

// 月度收益矩阵转换后的行，months 里的 null 是未来月份，渲染前必须判空
export interface MonthlyReturnRowView {
  year: number
  months: (number | null)[]
  yearly: number
}

export const api = {
  // 获取策略分类
  getCategories: () =>
    request<GetCategoriesResponse>("/strategies/categories"),

  // 获取策略列表
  getStrategies: (params?: StrategyListParams) =>
    request<StrategyListData>(`/strategies${toQuery(params)}`),

  // 获取策略详情
  getStrategy: (code: string) =>
    request<StrategyDetail>(`/strategies/${code}`),

  // 获取净值曲线（含数据转换）
  getEquityCurve: async (code: string): Promise<EquityCurveSeries> => {
    const d = await request<EquityCurveData>(`/strategies/${code}/equity-curve`)
    return {
      dates:     d.equity_curve.map(i => i.date),
      nav:       d.equity_curve.map(i => i.nav),
      benchmark: d.benchmark_curve.map(i => i.nav),
      drawdown:  d.drawdown_curve.map(i => i.drawdown),
    }
  },

  // 获取月度收益（含数据转换）
  getMonthlyReturns: async (code: string): Promise<{ rows: MonthlyReturnRowView[] }> => {
    const d = await request<MonthlyReturnsData>(`/strategies/${code}/monthly-returns`)
    const rows = d.matrix.map(row => ({
      year:   row.year,
      months: row.months,
      yearly: row.yearly_return,
    }))
    return { rows }
  },

  // 获取回测报告
  getBacktestReport: (code: string) =>
    request<BacktestReportData>(`/strategies/${code}/backtest-report`),

  // 获取交易记录
  getTrades: (code: string) =>
    request<TradeListData>(`/strategies/${code}/trades`),

  // 获取信号（支持按 type / status 过滤，空值参数自动剔除）
  getSignals: (code: string, params?: SignalListParams) =>
    request<SignalListData>(`/strategies/${code}/signals${toQuery(params)}`),

  // 获取信号详情
  getSignal: (id: string) =>
    request<SignalDetail>(`/signals/${id}`),
}
