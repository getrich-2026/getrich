import { useNavigate } from 'react-router-dom'
import Tag from './Tag'

interface SignalCardProps {
  id: string
  action: string
  direction: string
  symbol: string
  triggerPrice: number
  triggerTime: string
  urgency: string
  isRead: boolean
  strategyName: string
  confidence: number
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
  result,
  compact = false,
}: SignalCardProps) {
  const navigate = useNavigate()

  const urgencyTag =
    urgency === 'critical'
      ? ('red' as const)
      : urgency === 'high'
        ? ('orange' as const)
        : urgency === 'low'
          ? ('gray' as const)
          : ('blue' as const)

  return (
    <div
      className={`py-3 px-4 cursor-pointer transition-colors duration-150 hover:bg-[#F9FAFB] ${!isRead ? 'signal-unread' : ''}`}
      style={{ borderBottom: '1px solid var(--gr-border-light)' }}
      onClick={() => navigate(`/signals/${id}`)}
    >
      {/* Top row */}
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>
          {triggerTime}
        </span>
        <div className="flex items-center gap-2">
          <Tag variant={urgencyTag} size="default">
            {urgency === 'critical' ? '紧急' : urgency === 'high' ? '高' : urgency === 'low' ? '低' : '普通'}
          </Tag>
          {!isRead && (
            <div
              className="w-2 h-2 rounded-full"
              style={{ backgroundColor: 'var(--gr-accent-red)' }}
            />
          )}
        </div>
      </div>

      {/* Signal summary */}
      <div className="text-sm mb-1" style={{ color: 'var(--gr-text-primary)' }}>
        <span
          style={{
            color: action === 'buy' ? 'var(--gr-accent-green)' : 'var(--gr-accent-red)',
            fontWeight: 600,
          }}
        >
          {action === 'buy' ? '买入' : action === 'sell' ? '卖出' : '平仓'}
        </span>
        <span style={{ color: 'var(--gr-text-secondary)' }}>
          {' '}{direction === 'long' ? '做多' : direction === 'short' ? '做空' : ''} {symbol} @
          {triggerPrice.toFixed(2)}
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
