import { http } from './client'
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
export const getSignalFeed = (params?: SignalFeedParams) =>
  http.get<SignalFeedData>('/signals', { params })

// 获取未读信号统计
export const getUnreadSummary = () =>
  http.get<UnreadSummaryData>('/signals/unread-summary')

// 获取信号详情
export const getSignalDetail = (signalId: string) =>
  http.get<SignalDetail>(`/signals/${signalId}`)

// 标记信号已读
export const markSignalRead = (signalId: string) =>
  http.post<MarkReadData>(`/signals/${signalId}/read`)

// 记录信号执行反馈
export const executeSignal = (signalId: string, body?: ExecuteSignalBody) =>
  http.post<ExecuteSignalData>(`/signals/${signalId}/execute`, body ?? {})
