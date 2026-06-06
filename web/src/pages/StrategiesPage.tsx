import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getStrategyList } from '../api/strategies'
import type { Strategy } from '@/types/strategy'

/* ---------- MyStrategyItem 暂时保留 mock，等信号接口再换 ---------- */
interface MyStrategyItem {
  id: string
  date: string
  description: string
}

const mockMyStrategies: MyStrategyItem[] = [
  {
    id: 'STR_FUT_001',
    date: 'February 12, 2026',
    description: 'Notification of strategy "{name}" to add a new signal: The new signal is a long signal for the Hang Seng Index Futures (HSI2503) and is being monitored in real time.',
  },
  {
    id: 'STR_EQ_002',
    date: 'February 12, 2026',
    description: 'Notification of strategy "{name}" to add a new signal: The new signal is a long signal for the Hang Seng Index Futures (HSI2503) and is being monitored in real time.',
  },
  {
    id: 'STR_CTA_003',
    date: 'February 12, 2026',
    description: 'Notification of strategy "{name}" to add a new signal: The new signal is a long signal for the Hang Seng Index Futures (HSI2503) and is being monitored in real time.',
  },
  {
    id: 'STR_OPT_004',
    date: 'February 12, 2026',
    description: 'Notification of strategy "{name}" to add a new signal: The new signal is a long signal for the Hang Seng Index Futures (HSI2503) and is being monitored in real time.',
  },
]

/* ---------- Page Component ---------- */

export default function StrategiesPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['strategies'],
    queryFn: () => getStrategyList({ page: 1, page_size: 20 }),
  })

  const strategies = data?.data?.list ?? []

  return (
    <div className="max-w-[1100px] mx-auto px-6 py-6">
      {/* Strategy Cards */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold mb-4" style={{ color: 'var(--gr-text)' }}>
          策略精选
        </h1>

        {isError && (
          <div className="text-sm py-4" style={{ color: 'var(--gr-text-secondary)' }}>
            加载失败，请稍后重试
          </div>
        )}

        {isLoading ? (
          <div className="flex gap-4 overflow-x-auto pb-2 hide-scrollbar">
            {Array.from({ length: 4 }).map((_, i) => (
              <StrategyCardSkeleton key={i} />
            ))}
          </div>
        ) : (
          <div className="flex gap-4 overflow-x-auto pb-2 hide-scrollbar">
            {strategies.map((s: Strategy, i: number) => (
              <StrategyCard key={s.id} strategy={s} delay={i * 100} />
            ))}
          </div>
        )}
      </div>

      {/* My Strategies */}
      <div>
        <h2 className="text-lg font-semibold mb-4" style={{ color: 'var(--gr-text)' }}>
          我的策略
        </h2>
        <div className="space-y-3">
          {mockMyStrategies.map((s: MyStrategyItem, i: number) => (
            <MyStrategyCard key={s.id} item={s} delay={i * 80} />
          ))}
        </div>
      </div>
    </div>
  )
}

/* ---------- Sub Components ---------- */

// StrategyCard 现在直接用 API 的 Strategy 类型
// initialCapital API 没有，改成展示 subscriber_count（订阅人数）
function StrategyCard({ strategy, delay }: { strategy: Strategy; delay: number }) {
  const navigate = useNavigate()
  const riskColors: Record<string, { bg: string; text: string; label: string }> = {
    low:    { bg: '#F0FDF4', text: '#22C55E', label: '低风险' },
    medium: { bg: '#FFFBEB', text: '#F59E0B', label: '中风险' },
    high:   { bg: '#FEF2F2', text: '#E8473F', label: '高风险' },
  }
  const risk = riskColors[strategy.risk_level] || riskColors.medium

  return (
    <div
      className="flex-shrink-0 rounded-xl p-5 cursor-pointer card-shadow card-shadow-hover"
      style={{
        width: 280,
        background: 'var(--gr-card)',
        opacity: 0,
        animation: `fadeIn 0.2s ease-out ${delay}ms forwards`,
      }}
      onClick={() => navigate(`/strategies/${strategy.id}`)}
    >
      {/* Top row: name + risk tag */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold truncate" style={{ color: 'var(--gr-text)' }}>
          {strategy.name}
        </h3>
        <span
          className="text-[10px] font-semibold px-2 py-0.5 rounded-full flex-shrink-0 ml-2"
          style={{ background: risk.bg, color: risk.text }}
        >
          {risk.label}
        </span>
      </div>

      {/* Mini chart */}
      <MiniEquityChart />

      {/* Bottom metrics：initialCapital → subscriber_count */}
      <div className="grid grid-cols-3 gap-3 mt-4 pt-3" style={{ borderTop: '1px solid var(--gr-border-light)' }}>
        <div className="text-center">
          <div className="text-[10px] mb-1" style={{ color: 'var(--gr-text-tertiary)' }}>年化收益</div>
          <div className="text-sm font-bold tabular" style={{ color: strategy.performance.annualized_return >= 0 ? 'var(--gr-red)' : 'var(--gr-green)' }}>
            {strategy.performance.annualized_return >= 0 ? '+' : ''}
            {(strategy.performance.annualized_return * 100).toFixed(1)}%
          </div>
        </div>
        <div className="text-center">
          <div className="text-[10px] mb-1" style={{ color: 'var(--gr-text-tertiary)' }}>最大回撤</div>
          <div className="text-sm font-bold tabular" style={{ color: 'var(--gr-red)' }}>
            {(strategy.performance.max_drawdown * 100).toFixed(1)}%
          </div>
        </div>
        <div className="text-center">
          <div className="text-[10px] mb-1" style={{ color: 'var(--gr-text-tertiary)' }}>订阅人数</div>
          <div className="text-sm font-bold tabular" style={{ color: 'var(--gr-text-secondary)' }}>
            {strategy.subscriber_count}
          </div>
        </div>
      </div>
    </div>
  )
}

function StrategyCardSkeleton() {
  return (
    <div
      className="flex-shrink-0 rounded-xl p-4 card-shadow"
      style={{ width: 260, background: 'var(--gr-card)' }}
    >
      <div className="h-4 skeleton w-[80%] mb-3" />
      <div className="h-16 skeleton w-full mb-3" />
      <div className="grid grid-cols-3 gap-2">
        <div className="h-8 skeleton" />
        <div className="h-8 skeleton" />
        <div className="h-8 skeleton" />
      </div>
    </div>
  )
}

function MyStrategyCard({ item, delay }: { item: MyStrategyItem; delay: number }) {
  const navigate = useNavigate()

  return (
    <div
      className="rounded-xl p-4 cursor-pointer card-shadow card-shadow-hover"
      style={{
        background: 'var(--gr-card)',
        opacity: 0,
        animation: `fadeIn 0.2s ease-out ${delay}ms forwards`,
      }}
      onClick={() => navigate(`/strategies/${item.id}`)}
    >
      <h3 className="text-sm font-medium mb-1.5" style={{ color: 'var(--gr-red)' }}>
        {item.date}
      </h3>
      <p className="text-xs leading-relaxed" style={{ color: 'var(--gr-text-secondary)' }}>
        {item.description}
      </p>
    </div>
  )
}

/* ---------- Shared Micro Components ---------- */

function MiniEquityChart() {
  const strategyPoints  = 'M0,35 Q20,32 40,28 T80,22 T120,18 T160,14 T200,10 T240,8 T280,6'
  const benchmarkPoints = 'M0,38 Q20,36 40,34 T80,30 T120,28 T160,24 T200,22 T240,20 T280,18'

  return (
    <div className="h-10 w-full">
      <svg viewBox="0 0 280 40" className="w-full h-full" preserveAspectRatio="none">
        <line x1="0" y1="20" x2="280" y2="20" stroke="#F0F0F0" strokeWidth="0.5" />
        <path d={benchmarkPoints} fill="none" stroke="#3B82F6" strokeWidth="1" strokeDasharray="3,2" />
        <path d={strategyPoints}  fill="none" stroke="#E8473F" strokeWidth="1.5" />
      </svg>
    </div>
  )
}
