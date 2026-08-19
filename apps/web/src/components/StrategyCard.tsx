import { useNavigate } from 'react-router-dom'
import Tag from './Tag'

interface StrategyCardProps {
  id: string
  name: string
  riskLevel: string
  annualizedReturn: number
  maxDrawdown: number
  initialCapital: number
  miniChartData?: number[]
  compact?: boolean
}

export default function StrategyCard({
  id,
  name,
  riskLevel,
  annualizedReturn,
  maxDrawdown,
  initialCapital,
  compact = false,
}: StrategyCardProps) {
  const navigate = useNavigate()

  const riskTagVariant =
    riskLevel === 'high' ? ('red' as const) : riskLevel === 'medium' ? ('orange' as const) : ('gray' as const)

  return (
    <div
      className="rounded-[10px] p-4 cursor-pointer transition-colors duration-200 hover:bg-(--gr-card-hover)"
      style={{ backgroundColor: 'var(--gr-card-bg)' }}
      onClick={() => navigate(`/strategies/${id}`)}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <h4
          className="text-sm font-medium truncate"
          style={{ color: 'var(--gr-text-primary)' }}
        >
          {name}
        </h4>
        <Tag variant={riskTagVariant} size="default">
          {riskLevel === 'high' ? '高风险' : riskLevel === 'medium' ? '中风险' : '低风险'}
        </Tag>
      </div>

      {/* Mini Chart Placeholder */}
      {!compact && (
        <div className="h-[60px] mb-3 relative overflow-hidden rounded-md">
          <svg viewBox="0 0 300 60" className="w-full h-full" preserveAspectRatio="none">
            <path
              d="M0,45 Q30,42 60,38 T120,32 T180,28 T240,22 T300,15"
              fill="none"
              stroke="var(--gr-accent-red)"
              strokeWidth="1.5"
            />
          </svg>
        </div>
      )}

      {/* Metrics */}
      <div className="flex items-center justify-between">
        <div className="flex flex-col items-center">
          <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>
            年化收益
          </span>
          <span
            className="text-xs font-semibold tabular-nums"
            style={{
              color: annualizedReturn >= 0 ? 'var(--gr-accent-green)' : 'var(--gr-accent-red)',
            }}
          >
            {annualizedReturn >= 0 ? '+' : ''}
            {(annualizedReturn * 100).toFixed(1)}%
          </span>
        </div>
        <div className="flex flex-col items-center">
          <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>
            最大回撤
          </span>
          <span
            className="text-xs font-semibold tabular-nums"
            style={{ color: 'var(--gr-accent-red)' }}
          >
            {(maxDrawdown * 100).toFixed(1)}%
          </span>
        </div>
        <div className="flex flex-col items-center">
          <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>
            初始资金
          </span>
          <span
            className="text-xs font-semibold tabular-nums"
            style={{ color: 'var(--gr-text-secondary)' }}
          >
            ¥{(initialCapital / 10000).toFixed(0)}万
          </span>
        </div>
      </div>
    </div>
  )
}
