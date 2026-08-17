// 后端基址统一由 VITE_API_BASE_URL 提供（值里已含 /v1 前缀），与 src/api/client.ts 一致。
// 不要在源码里硬编码服务器地址 —— 本仓库是公开仓库。
const BASE_URL = import.meta.env.VITE_API_BASE_URL

// 统一请求封装，自动校验 code 并抛错
async function request<T>(url: string): Promise<T> {
  const res = await fetch(BASE_URL + url)
  const json = await res.json()
  if (json.code !== 0) throw new Error(json.message)
  return json.data
}

export const api = {
  // 获取策略分类
  getCategories: () =>
    request<any>("/strategies/categories"),

  // 获取策略列表
  getStrategies: (params?: { page?: number; page_size?: number }) => {
    const query = new URLSearchParams(params as any).toString()
    return request<any>(`/strategies${query ? "?" + query : ""}`)
  },

  // 获取策略详情
  getStrategy: (code: string) =>
    request<any>(`/strategies/${code}`),

  // 获取净值曲线（含数据转换）
  getEquityCurve: async (code: string) => {
    const d = await request<any>(`/strategies/${code}/equity-curve`)
    return {
      dates:     (d.equity_curve    as any[]).map(i => i.date),
      nav:       (d.equity_curve    as any[]).map(i => i.nav),
      benchmark: (d.benchmark_curve as any[]).map(i => i.nav),
      drawdown:  (d.drawdown_curve  as any[]).map(i => i.drawdown),
    }
  },

  // 获取月度收益（含数据转换）
  getMonthlyReturns: async (code: string) => {
    const d = await request<any>(`/strategies/${code}/monthly-returns`)
    const rows = (d.matrix as any[]).map(row => ({
      year:   row.year           as number,
      months: row.months         as (number | null)[],
      yearly: row.yearly_return  as number,
    }))
    return { rows }
  },

  // 获取回测报告
  getBacktestReport: (code: string) =>
    request<any>(`/strategies/${code}/backtest-report`),

  // 获取交易记录
  getTrades: (code: string) =>
    request<any>(`/strategies/${code}/trades`),

  // 获取信号（支持按 type / status 过滤，空值参数自动剔除）
  getSignals: (code: string, params?: { type?: string; status?: string; page?: number; page_size?: number }) => {
    const p = Object.fromEntries(
      Object.entries(params ?? {}).filter(([, v]) => v != null)
    )
    const query = new URLSearchParams(p as any).toString()
    return request<any>(`/strategies/${code}/signals${query ? '?' + query : ''}`)
  },

  // 获取信号详情
  getSignal: (id: string) =>
    request<any>(`/signals/${id}`),
}