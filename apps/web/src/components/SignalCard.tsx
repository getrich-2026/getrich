import { useNavigate } from 'react-router-dom'
import Tag from './Tag'

interface SignalCardProps {
  id: string
  action: string
  direction: string
  symbol: string
  triggerPrice: number | null   // null = 市价单
  triggerTime: string
  urgency: string
  isRead: boolean
  strategyName: string
  confidence: number
  status?: string               // active | expired | ...
  result?: {
    returnPct: number
    status: string
  }
  compact?: boolean
}

export default function SignalCard({
  id,
  action,
  direction,
  symbol,
  triggerPrice,
  triggerTime,
  urgency,
  isRead,
  strategyName,
  confidence,
  status,
  result,
  compact = false,
}: SignalCardProps) {
  const navigate = useNavigate()

  const urgencyTag =
    urgency === 'critical' ? ('red'    as const) :
    urgency === 'high'     ? ('orange' as const) :
    urgency === 'low'      ? ('gray'   as const) :
                             ('blue'   as const)

  const urgencyLabel =
    urgency === 'critical' ? '紧急' :
    urgency === 'high'     ? '高'   :
    urgency === 'low'      ? '低'   : '普通'

  const actionLabel =
    action === 'buy'  ? '买入' :
    action === 'sell' ? '卖出' : '平仓'

  const actionColor =
    action === 'buy' ? 'var(--gr-accent-green)' : 'var(--gr-accent-red)'

  const directionLabel =
    direction === 'long'  ? '做多' :
    direction === 'short' ? '做空' : ''

  const priceLabel =
    triggerPrice != null ? `@ ${triggerPrice.toFixed(2)}` : '@ 市价'

  const isExpired = status === 'expired'

  return (
    <div
      className={`py-3 px-4 cursor-pointer transition-colors duration-150 hover:bg-[#F9FAFB] ${!isRead ? 'signal-unread' : ''} ${isExpired ? 'opacity-50' : ''}`}
      style={{ borderBottom: '1px solid var(--gr-border-light)' }}
      onClick={() => navigate(`/signals/${id}`)}
    >
      {/* Top row */}
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>
          {triggerTime}
        </span>
        <div className="flex items-center gap-2">
          {/* 过期标记 */}
          {isExpired && (
            <span
              className="text-xs px-1.5 py-0.5 rounded"
              style={{
                background: 'var(--gr-bg)',
                color: 'var(--gr-text-tertiary)',
                border: '1px solid var(--gr-border)',
              }}
            >
              已过期
            </span>
          )}
          <Tag variant={urgencyTag} size="default">{urgencyLabel}</Tag>
          {!isRead && (
            <div
              className="w-2 h-2 rounded-full flex-shrink-0"
              style={{ backgroundColor: 'var(--gr-accent-red)' }}
            />
          )}
        </div>
      </div>

      {/* Signal summary */}
      <div className="text-sm mb-1" style={{ color: 'var(--gr-text-primary)' }}>
        <span style={{ color: actionColor, fontWeight: 600 }}>
          {actionLabel}
        </span>
        <span style={{ color: 'var(--gr-text-secondary)' }}>
          {' '}{directionLabel} {symbol} {priceLabel}
        </span>
        {result && (
          <span
            className="ml-2 text-xs tabular-nums"
            style={{
              color: result.returnPct >= 0 ? 'var(--gr-accent-green)' : 'var(--gr-accent-red)',
            }}
          >
            → 平仓 {result.returnPct >= 0 ? '+' : ''}
            {(result.returnPct * 100).toFixed(2)}%
          </span>
        )}
      </div>

      {/* Strategy source */}
      {!compact && (
        <div className="text-xs" style={{ color: 'var(--gr-text-secondary)' }}>
          {strategyName} · 置信度 {Math.round(confidence * 100)}%
        </div>
      )}
    </div>
  )
}