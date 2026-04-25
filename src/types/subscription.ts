// ===== 公共 =====

// 信号紧急程度枚举，signal.ts 里的 urgency 字段同一套值
// 联调稳定后建议挪到 types/common.ts 统一管理
export type UrgencyLevel = 'low' | 'normal' | 'high' | 'critical'

// 推送渠道，GET response 只有两个字段，以 PUT body 为准补全
export interface SignalSettingsChannels {
  app_push: boolean
  wechat_service: boolean
  sms: boolean
  email: boolean
  websocket: boolean
}

// ===== 订阅策略 =====

export interface SubscribeStrategyBody {
  plan_type: 'monthly' | 'yearly'
  auto_renew?: boolean          // 默认 true
  payment_source: 'wechat' | 'alipay' | 'bank' | 'apple_pay' | 'stripe'
}

export interface SubscriptionPayment {
  order_id: string
  amount: number
  payment_source: string
  expire_time: string           // 支付二维码过期时间，不是订阅到期时间
}

export interface SubscribeStrategyData {
  subscription_id: string
  status: 'pending_payment' | 'active' | 'cancelled' | 'expired'
  plan_type: 'monthly' | 'yearly'
  start_date: string
  expire_date: string
  payment: SubscriptionPayment | null   // 只有 status === 'pending_payment' 时有值
}

// ===== 取消订阅策略 =====

export interface UnsubscribeStrategyBody {
  reason?: string
}

export interface UnsubscribeStrategyData {
  strategy_id: string
  status: 'cancelled'
  access_until: string    // 已付费周期内仍可访问到该日期，UI 提示"可使用至 XX 日"
}

// ===== 查询订阅状态 =====

export interface SubscriptionPrice {
  monthly: number
  yearly: number
}

export interface SubscriptionStatusData {
  is_subscribed: boolean
  subscription_id: string | null
  status: 'active' | 'pending_payment' | 'cancelled' | 'expired' | null
  plan_type: 'monthly' | 'yearly' | null
  start_date: string | null
  expire_date: string | null
  auto_renew: boolean | null
  subscription_price: SubscriptionPrice   // 未订阅时也会返回，直接喂给订阅弹窗定价展示
}

// ===== 获取策略推送配置 =====

export interface StrategySignalSettings {
  strategy_id: string
  enabled: boolean
  channels: SignalSettingsChannels
  urgency_filter: UrgencyLevel[]      // 只接收这些等级的信号推送
  confidence_threshold: number        // 低于此置信度不推送
  notify_entry_only: boolean          // 只推送入场信号
}

// ===== 更新策略推送配置 =====

export interface UpdateSignalSettingsBody {
  enabled?: boolean
  channels?: Partial<SignalSettingsChannels>   // 只传需要修改的渠道
  urgency_filter?: UrgencyLevel[]
  confidence_threshold?: number               // 0 ~ 1
  notify_entry_only?: boolean
}

export interface UpdateSignalSettingsData {
  strategy_id: string
  updated: boolean
}