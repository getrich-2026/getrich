import { http } from './client'
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
export const subscribeStrategy = (strategyId: string, body: SubscribeStrategyBody) =>
  http.post<SubscribeStrategyData>(`/strategies/${strategyId}/subscribe`, body)

// 取消订阅策略
export const unsubscribeStrategy = (strategyId: string, body?: UnsubscribeStrategyBody) =>
  http.post<UnsubscribeStrategyData>(`/strategies/${strategyId}/unsubscribe`, body ?? {})

// 查询策略订阅状态
export const getSubscriptionStatus = (strategyId: string) =>
  http.get<SubscriptionStatusData>(`/strategies/${strategyId}/subscription`)

// 获取策略维度推送配置
export const getStrategySignalSettings = (strategyId: string) =>
  http.get<StrategySignalSettings>(`/strategies/${strategyId}/signal-settings`)

// 更新策略维度推送配置
export const updateStrategySignalSettings = (
  strategyId: string,
  body: UpdateSignalSettingsBody
) => http.put<UpdateSignalSettingsData>(`/strategies/${strategyId}/signal-settings`, body)
