import apiClient from './client'
import type { ApiResponse } from '@/types/common'
import type {
  SignalFeedParams,
  SignalFeedData,
  UnreadSummaryData,
  SignalDetail,
  MarkReadData,
  ExecuteSignalBody,
  ExecuteSignalData,
} from '@/types/signal'

// 获取用户信号流（跨策略聚合）
export const getSignalFeed = (params?: SignalFeedParams) => {
  return apiClient.get<ApiResponse<SignalFeedData>>('/signals', { params })
}

// 获取未读信号统计
export const getUnreadSummary = () => {
  return apiClient.get<ApiResponse<UnreadSummaryData>>('/signals/unread-summary')
}

// 获取信号详情
export const getSignalDetail = (signalId: string) => {
  return apiClient.get<ApiResponse<SignalDetail>>(`/signals/${signalId}`)
}

// 标记信号已读
export const markSignalRead = (signalId: string) => {
  return apiClient.post<ApiResponse<MarkReadData>>(`/signals/${signalId}/read`)
}

// 记录信号执行反馈
export const executeSignal = (signalId: string, body?: ExecuteSignalBody) => {
  return apiClient.post<ApiResponse<ExecuteSignalData>>(
    `/signals/${signalId}/execute`,
    body ?? {}
  )
}