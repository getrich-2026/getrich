import apiClient from './client'
import type { ApiResponse } from '@/types/common'
import type {
  SubscribeStrategyBody,
  SubscribeStrategyData,
  UnsubscribeStrategyBody,
  UnsubscribeStrategyData,
  SubscriptionStatusData,
  StrategySignalSettings,
  UpdateSignalSettingsBody,
  UpdateSignalSettingsData,
} from '@/types/subscription'

// 订阅策略
export const subscribeStrategy = (
  strategyId: string,
  body: SubscribeStrategyBody
) => {
  return apiClient.post<ApiResponse<SubscribeStrategyData>>(
    `/strategies/${strategyId}/subscribe`,
    body
  )
}

// 取消订阅策略
export const unsubscribeStrategy = (
  strategyId: string,
  body?: UnsubscribeStrategyBody
) => {
  return apiClient.post<ApiResponse<UnsubscribeStrategyData>>(
    `/strategies/${strategyId}/unsubscribe`,
    body ?? {}
  )
}

// 查询策略订阅状态
export const getSubscriptionStatus = (strategyId: string) => {
  return apiClient.get<ApiResponse<SubscriptionStatusData>>(
    `/strategies/${strategyId}/subscription`
  )
}

// 获取策略维度推送配置
export const getStrategySignalSettings = (strategyId: string) => {
  return apiClient.get<ApiResponse<StrategySignalSettings>>(
    `/strategies/${strategyId}/signal-settings`
  )
}

// 更新策略维度推送配置
export const updateStrategySignalSettings = (
  strategyId: string,
  body: UpdateSignalSettingsBody
) => {
  return apiClient.put<ApiResponse<UpdateSignalSettingsData>>(
    `/strategies/${strategyId}/signal-settings`,
    body
  )
}