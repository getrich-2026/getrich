import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

export default function StrategiesPage() {
  const navigate = useNavigate()

  const { data, isLoading, isError } = useQuery({
    queryKey: ['strategies'],
    queryFn: () => api.getStrategies({ page: 1, page_size: 20 }),
  })

  const strategies: any[] = data?.list ?? []
  const subscribed = strategies.filter(s => s.is_subscribed)

  return (
    <div className="max-w-[1100px] mx-auto px-6 py-6">

      {/* ── 策略精选 ── */}
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
            {Array.from({ length: 4 }).map((_, i) => <StrategyCardSkeleton key={i} />)}
          </div>
        ) : (
          <div className="flex gap-4 overflow-x-auto pb-2 hide-scrollbar">
            {strategies.map((s, i) => (
              <StrategyCard key={s.id} strategy={s} delay={i * 80} />
            ))}
          </div>
        )}
      </div>

      {/* ── 我的策略 ── */}
      <div>
        <h2 className="text-lg font-semibold mb-4" style={{ color: 'var(--gr-text)' }}>
          我的策略
        </h2>

        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 2 }).map((_, i) => <MyStrategyCardSkeleton key={i} />)}
          </div>
        ) : subscribed.length === 0 ? (
          <div
            className="rounded-xl p-8 text-center text-sm card-shadow"
            style={{ background: 'var(--gr-card)', color: 'var(--gr-text-tertiary)' }}
          >
            暂未订阅任何策略
            <button
              className="block mx-auto mt-2 text-xs"
              style={{ color: 'var(--gr-red)' }}
              onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
            >
              浏览策略精选 ↑
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            {subscribed.map((s, i) => (
              <MyStrategyCard key={s.id} strategy={s} delay={i * 80} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

/* ── Strategy Card（精选） ── */

const riskColors: Record<string, { bg: string; text: string; label: string }> = {
  low:    { bg: '#F0FDF4', text: '#22C55E', label: '低风险' },
  medium: { bg: '#FFFBEB', text: '#F59E0B', label: '中风险' },
  high:   { bg: '#FEF2F2', text: '#E8473F', label: '高风险' },
}

function StrategyCard({ strategy, delay }: { strategy: any; delay: number }) {
  const navigate = useNavigate()
  const risk = riskColors[strategy.risk_level] ?? riskColors.medium
  const perf = strategy.performance

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
      {/* 名称 + 风险标签 */}
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

      {/* 迷你走势图 */}
      <MiniEquityChart />

      {/* 指标 */}
      <div
        className="grid grid-cols-3 gap-3 mt-4 pt-3"
        style={{ borderTop: '1px solid var(--gr-border-light)' }}
      >
        <div className="text-center">
          <div className="text-[10px] mb-1" style={{ color: 'var(--gr-text-tertiary)' }}>年化收益</div>
          <div
            className="text-sm font-bold tabular"
            style={{ color: perf?.annualized_return >= 0 ? 'var(--gr-red)' : 'var(--gr-green)' }}
          >
            {perf ? `${perf.annualized_return >= 0 ? '+' : ''}${(perf.annualized_return * 100).toFixed(1)}%` : '-'}
          </div>
        </div>
        <div className="text-center">
          <div className="text-[10px] mb-1" style={{ color: 'var(--gr-text-tertiary)' }}>最大回撤</div>
          <div className="text-sm font-bold tabular" style={{ color: 'var(--gr-red)' }}>
            {perf ? `${(perf.max_drawdown * 100).toFixed(1)}%` : '-'}
          </div>
        </div>
        <div className="text-center">
          <div className="text-[10px] mb-1" style={{ color: 'var(--gr-text-tertiary)' }}>订阅人数</div>
          <div className="text-sm font-bold tabular" style={{ color: 'var(--gr-text-secondary)' }}>
            {strategy.subscriber_count ?? '-'}
          </div>
        </div>
      </div>
    </div>
  )
}

function StrategyCardSkeleton() {
  return (
    <div
      className="flex-shrink-0 rounded-xl p-5 card-shadow"
      style={{ width: 280, background: 'var(--gr-card)' }}
    >
      <div className="h-4 skeleton w-[70%] mb-3 rounded" />
      <div className="h-10 skeleton w-full mb-4 rounded" />
      <div className="grid grid-cols-3 gap-2">
        <div className="h-8 skeleton rounded" />
        <div className="h-8 skeleton rounded" />
        <div className="h-8 skeleton rounded" />
      </div>
    </div>
  )
}

/* ── My Strategy Card（已订阅） ── */

function MyStrategyCard({ strategy, delay }: { strategy: any; delay: number }) {
  const navigate = useNavigate()
  const perf = strategy.performance

  return (
    <div
      className="rounded-xl p-4 cursor-pointer card-shadow card-shadow-hover"
      style={{
        background: 'var(--gr-card)',
        opacity: 0,
        animation: `fadeIn 0.2s ease-out ${delay}ms forwards`,
      }}
      onClick={() => navigate(`/strategies/${strategy.id}`)}
    >
      <div className="flex items-center justify-between">
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold truncate mb-1" style={{ color: 'var(--gr-text)' }}>
            {strategy.name}
          </h3>
          <p className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>
            {strategy.category?.name}
            {strategy.asset_class ? ` · ${strategy.asset_class}` : ''}
          </p>
        </div>
        <div className="flex gap-4 ml-4 flex-shrink-0 text-right">
          <div>
            <div className="text-[10px] mb-0.5" style={{ color: 'var(--gr-text-tertiary)' }}>年化收益</div>
            <div
              className="text-sm font-bold tabular"
              style={{ color: perf?.annualized_return >= 0 ? '#16A34A' : '#DC2626' }}
            >
              {perf
                ? `${perf.annualized_return >= 0 ? '+' : ''}${(perf.annualized_return * 100).toFixed(1)}%`
                : '-'}
            </div>
          </div>
          <div>
            <div className="text-[10px] mb-0.5" style={{ color: 'var(--gr-text-tertiary)' }}>最大回撤</div>
            <div className="text-sm font-bold tabular" style={{ color: '#DC2626' }}>
              {perf ? `${(perf.max_drawdown * 100).toFixed(1)}%` : '-'}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function MyStrategyCardSkeleton() {
  return (
    <div className="rounded-xl p-4 card-shadow" style={{ background: 'var(--gr-card)' }}>
      <div className="flex items-center justify-between">
        <div className="flex-1">
          <div className="h-4 skeleton w-[50%] mb-2 rounded" />
          <div className="h-3 skeleton w-[30%] rounded" />
        </div>
        <div className="flex gap-4 ml-4">
          <div className="h-8 skeleton w-14 rounded" />
          <div className="h-8 skeleton w-14 rounded" />
        </div>
      </div>
    </div>
  )
}

/* ── Mini Chart ── */

function MiniEquityChart() {
  return (
    <div className="h-10 w-full">
      <svg viewBox="0 0 280 40" className="w-full h-full" preserveAspectRatio="none">
        <line x1="0" y1="20" x2="280" y2="20" stroke="#F0F0F0" strokeWidth="0.5" />
        <path
          d="M0,38 Q20,36 40,34 T80,30 T120,28 T160,24 T200,22 T240,20 T280,18"
          fill="none" stroke="#3B82F6" strokeWidth="1" strokeDasharray="3,2"
        />
        <path
          d="M0,35 Q20,32 40,28 T80,22 T120,18 T160,14 T200,10 T240,8 T280,6"
          fill="none" stroke="#E8473F" strokeWidth="1.5"
        />
      </svg>
    </div>
  )
}