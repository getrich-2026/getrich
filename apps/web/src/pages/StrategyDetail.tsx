import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Share2 } from 'lucide-react'
import Tag from '@/components/Tag'
import MetricCard from '@/components/MetricCard'
import EquityChart from '@/components/EquityChart'
import MonthlyHeatmap from '@/components/MonthlyHeatmap'
import SignalCard from '@/components/SignalCard'
import { StrategyActionBar } from '@/components/BottomActionBar'
import { api } from '@/lib/api'

const tabs = ['策略说明', '回测报告', '历史交易', '最近信号']

const riskLevelMap: Record<string, string> = {
  low: '低风险',
  medium: '中风险',
  high: '高风险',
}

export default function StrategyDetail() {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const [activeTab, setActiveTab] = useState(0)

  const { data: strategy, isLoading: strategyLoading } = useQuery({
    queryKey: ['strategy', id],
    queryFn: () => api.getStrategy(id!),
    enabled: !!id,
  })

  const { data: signalsData, isLoading: signalsLoading } = useQuery({
    queryKey: ['signals', id],
    queryFn: () => api.getSignals(id!),
    enabled: !!id,
  })

  const loading = strategyLoading
  const s = strategy
  const perf = s?.performance
  const signals = signalsData?.list ?? []

  if (!loading && !s) {
    return (
      <div className="flex items-center justify-center h-64" style={{ color: 'var(--gr-text-secondary)' }}>
        策略不存在
      </div>
    )
  }

  return (
    <div className="pb-24">
      <div className="max-w-[1100px] mx-auto px-6 py-6">

        {/* ========== Section 1: Header ========== */}
        <div className="mb-5">
          {loading ? (
            <HeaderSkeleton />
          ) : (
            <div className="fade-in">
              <div className="flex items-start justify-between mb-2">
                <div className="flex-1 min-w-0">
                  <button
                    onClick={() => navigate('/strategies')}
                    className="flex items-center gap-1 mb-2 transition-colors duration-150 hover:text-[var(--gr-text)]"
                    style={{ color: 'var(--gr-text-secondary)', fontSize: '13px' }}
                  >
                    <ArrowLeft size={14} />
                    <span>策略库</span>
                  </button>
                  <h1
                    className="text-2xl font-bold tracking-tight"
                    style={{ color: 'var(--gr-text)', letterSpacing: '-0.01em' }}
                  >
                    {s.name}
                  </h1>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  {s.is_subscribed ? (
                    <>
                      <Tag variant="green" size="lg">已订阅</Tag>
                      <button
                        className="p-2 rounded-md hover:bg-[var(--gr-bg)] transition-colors"
                        style={{ color: 'var(--gr-text-secondary)' }}
                      >
                        <Share2 size={16} />
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        className="px-4 py-2 rounded-md text-sm font-semibold text-white"
                        style={{ background: 'var(--gr-red)' }}
                      >
                        立即订阅
                      </button>
                      <button
                        className="flex items-center gap-1 px-3 py-2 rounded-md text-xs font-medium hover:bg-[var(--gr-bg)] transition-colors"
                        style={{ color: 'var(--gr-text-secondary)', border: '1px solid var(--gr-border)' }}
                      >
                        <Share2 size={14} />
                        分享
                      </button>
                    </>
                  )}
                </div>
              </div>

              {/* Meta tags */}
              <div className="flex items-center gap-2 mb-2 flex-wrap">
                <Tag variant="blue">{s.category?.name}</Tag>
                <span style={{ color: 'var(--gr-text-tertiary)' }}>·</span>
                <Tag variant="orange">{riskLevelMap[s.risk_level] ?? s.risk_level}</Tag>
                <span style={{ color: 'var(--gr-text-tertiary)' }}>·</span>
                <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>
                  {s.asset_class}
                </span>
                <span style={{ color: 'var(--gr-text-tertiary)' }}>·</span>
                <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>
                  更新于 {new Date(s.updated_at).toLocaleDateString('zh-CN')}
                </span>
              </div>

              {/* Tags */}
              <div className="flex gap-2 flex-wrap">
                {s.tags?.map((tag: string) => (
                  <Tag key={tag} variant="blue">{tag}</Tag>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ========== Section 2: 6-Grid Metrics ========== */}
        <div className="grid grid-cols-3 gap-3 mb-5">
          <MetricCard
            label="年化收益"
            value={perf ? `+${(perf.annualized_return * 100).toFixed(2)}%` : '-'}
            color="green"
            tooltip="策略自运行以来的年化复合收益率"
            delay={0}
            isLoading={loading}
          />
          <MetricCard
            label="最大回撤"
            value={perf ? `${(perf.max_drawdown * 100).toFixed(2)}%` : '-'}
            color="red"
            tooltip="策略历史上从高点到低点的最大亏损幅度"
            delay={50}
            isLoading={loading}
          />
          <MetricCard
            label="夏普比率"
            value={perf ? perf.sharpe_ratio.toFixed(2) : '-'}
            color={perf?.sharpe_ratio >= 1 ? 'green' : 'neutral'}
            tooltip="每单位风险所获得的超额回报"
            delay={100}
            isLoading={loading}
          />
          <MetricCard
            label="胜率"
            value={perf ? `${(perf.win_rate * 100).toFixed(2)}%` : '-'}
            color={perf?.win_rate >= 0.5 ? 'green' : 'red'}
            tooltip="盈利交易次数占总交易次数的比例"
            delay={150}
            isLoading={loading}
          />
          <MetricCard
            label="总收益率"
            value={perf ? `+${(perf.total_return * 100).toFixed(2)}%` : '-'}
            color="green"
            tooltip="策略全周期累计收益率"
            delay={200}
            isLoading={loading}
          />
          <MetricCard
            label="总交易次数"
            value={perf ? `${perf.total_trades}次` : '-'}
            color="neutral"
            tooltip="回测期间总交易次数"
            delay={250}
            isLoading={loading}
          />
        </div>

        {/* ========== Section 3: Equity Curve ========== */}
        <div className="rounded-xl p-5 mb-5 card-shadow" style={{ background: 'var(--gr-card)' }}>
          <EquityChart strategyId={id} isLoading={loading} />
        </div>

        {/* ========== Section 4: Monthly Heatmap ========== */}
        <div className="rounded-xl p-5 mb-5 card-shadow" style={{ background: 'var(--gr-card)' }}>
          <MonthlyHeatmap strategyId={id} isLoading={loading} />
        </div>

        {/* ========== Section 5: Tabs ========== */}
        <div className="rounded-xl overflow-hidden card-shadow" style={{ background: 'var(--gr-card)' }}>
          <div className="flex" style={{ borderBottom: '1px solid var(--gr-border)' }}>
            {tabs.map((tab, i) => (
              <button
                key={tab}
                onClick={() => setActiveTab(i)}
                className="relative px-4 py-2.5 text-sm font-medium transition-colors duration-150"
                style={{ color: activeTab === i ? 'var(--gr-text)' : 'var(--gr-text-secondary)' }}
              >
                {tab}
                {activeTab === i && (
                  <div
                    className="absolute bottom-0 left-0 right-0 h-0.5"
                    style={{ background: 'var(--gr-red)' }}
                  />
                )}
              </button>
            ))}
          </div>

          <div className="p-5">
            {loading ? (
              <div className="space-y-3">
                <div className="h-4 skeleton w-full" />
                <div className="h-4 skeleton w-[90%]" />
                <div className="h-4 skeleton w-[70%]" />
              </div>
            ) : (
              <div className="fade-in">
                {activeTab === 0 && (
                  <StrategyDescTab detailHtml={s.detail_html} />
                )}
                {activeTab === 1 && (
                  <BacktestTab strategy={s} />
                )}
                {activeTab === 2 && (
                  <TradesTab strategyId={id!} />
                )}
                {activeTab === 3 && (
                  <SignalsTab
                    signals={signals}
                    isLoading={signalsLoading}
                    strategyName={s.name}
                    onViewAll={() => navigate('/signals')}
                  />
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Bottom Action Bar */}
      <StrategyActionBar
        isSubscribed={s?.is_subscribed ?? false}
        monthlyPrice={s?.subscription_price?.monthly ?? 0}
        yearlyPrice={s?.subscription_price?.yearly ?? 0}
        expireDate={s?.subscription_info?.expire_date ?? ''}
      />
    </div>
  )
}

/* ---------- Tab: 策略说明 ---------- */

function StrategyDescTab({ detailHtml }: { detailHtml: string }) {
  return (
    <div
      className="prose prose-sm max-w-none"
      style={{ color: 'var(--gr-text-secondary)', lineHeight: 1.7 }}
      dangerouslySetInnerHTML={{ __html: detailHtml }}
    />
  )
}

/* ---------- Tab: 回测报告 ---------- */

function BacktestTab({ strategy }: { strategy: any }) {
  const perf   = strategy?.performance
  const period = strategy?.backtest_period

  return (
    <div>
      <div className="grid grid-cols-4 gap-4 mb-6">
        {[
          { label: '回测开始', value: period?.start ?? '-' },
          { label: '回测结束', value: period?.end ?? '-' },
          { label: '总收益率', value: perf ? `+${(perf.total_return * 100).toFixed(1)}%` : '-', color: 'var(--gr-green)' },
          { label: '总交易次数', value: perf ? `${perf.total_trades}次` : '-' },
        ].map((item) => (
          <div key={item.label} className="text-center">
            <div className="text-xs mb-1" style={{ color: 'var(--gr-text-tertiary)' }}>
              {item.label}
            </div>
            <div
              className="text-lg font-semibold tabular"
              style={{ color: (item as any).color || 'var(--gr-text)' }}
            >
              {item.value}
            </div>
          </div>
        ))}
      </div>

      <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--gr-text)' }}>绩效指标</h3>
      <div className="grid grid-cols-2 gap-3">
        {[
          { label: '年化收益率', value: perf ? `+${(perf.annualized_return * 100).toFixed(2)}%` : '-' },
          { label: '最大回撤',   value: perf ? `${(perf.max_drawdown * 100).toFixed(2)}%` : '-' },
          { label: '夏普比率',   value: perf ? perf.sharpe_ratio.toFixed(2) : '-' },
          { label: 'Sortino 比率', value: perf ? perf.sortino_ratio.toFixed(2) : '-' },
          { label: '胜率',       value: perf ? `${(perf.win_rate * 100).toFixed(2)}%` : '-' },
        ].map(({ label, value }) => (
          <div
            key={label}
            className="flex justify-between items-center px-4 h-10 rounded-lg"
            style={{ background: 'var(--gr-bg)' }}
          >
            <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>{label}</span>
            <span className="text-sm font-medium" style={{ color: 'var(--gr-text)' }}>{value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ---------- Tab: 历史交易 ---------- */

function TradesTab({ strategyId }: { strategyId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['trades', strategyId],
    queryFn:  () => api.getTrades(strategyId),
  })

  const list = data?.list ?? []

  if (isLoading) {
    return (
      <div className="space-y-2">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-12 skeleton rounded-lg" />
        ))}
      </div>
    )
  }

  if (list.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 gap-2">
        <span style={{ fontSize: 32 }}>📭</span>
        <span className="text-sm" style={{ color: 'var(--gr-text-tertiary)' }}>
          暂无历史交易记录
        </span>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr style={{ borderBottom: '1px solid var(--gr-border)' }}>
            {['时间', '合约', '方向', '开仓价', '平仓价', '盈亏'].map(h => (
              <th
                key={h}
                className="pb-2 text-xs font-medium text-left pr-4"
                style={{ color: 'var(--gr-text-tertiary)' }}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {list.map((t: any) => (
            <tr key={t.id} style={{ borderBottom: '1px solid var(--gr-border)' }}>
              <td className="py-3 pr-4 text-xs" style={{ color: 'var(--gr-text-secondary)' }}>
                {new Date(t.open_time ?? t.created_at).toLocaleDateString('zh-CN')}
              </td>
              <td className="py-3 pr-4 font-medium" style={{ color: 'var(--gr-text)' }}>
                {t.symbol}
              </td>
              <td className="py-3 pr-4">
                <span
                  className="px-2 py-0.5 rounded text-xs font-medium"
                  style={{
                    background: t.direction === 'long'
                      ? 'rgba(34,197,94,0.1)'
                      : 'rgba(239,68,68,0.1)',
                    color: t.direction === 'long' ? '#16A34A' : '#DC2626',
                  }}
                >
                  {t.direction === 'long' ? '多' : '空'}
                </span>
              </td>
              <td className="py-3 pr-4 tabular" style={{ color: 'var(--gr-text)' }}>
                {t.open_price ?? '-'}
              </td>
              <td className="py-3 pr-4 tabular" style={{ color: 'var(--gr-text)' }}>
                {t.close_price ?? '-'}
              </td>
              <td
                className="py-3 tabular font-medium"
                style={{ color: (t.pnl ?? 0) >= 0 ? '#16A34A' : '#DC2626' }}
              >
                {t.pnl != null
                  ? `${t.pnl >= 0 ? '+' : ''}${t.pnl.toFixed(2)}`
                  : '-'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ---------- Tab: 最近信号 ---------- */

function SignalsTab({
  signals,
  isLoading,
  strategyName,
  onViewAll,
}: {
  signals: any[]
  isLoading: boolean
  strategyName: string
  onViewAll: () => void
}) {
  if (isLoading) {
    return (
      <div className="space-y-3">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="h-16 skeleton w-full rounded-lg" />
        ))}
      </div>
    )
  }

  if (signals.length === 0) {
    return (
      <div className="text-center py-8" style={{ color: 'var(--gr-text-tertiary)' }}>
        暂无信号
      </div>
    )
  }

  return (
    <div>
      {signals.map((sig: any) => {
        // action: buy=做多 sell=做空 open=仅开仓标记（看 signal_type 兜底）
        const direction =
          sig.action === 'sell' ? 'short' :
          sig.action === 'buy'  ? 'long'  :
          sig.signal_type === 'exit' ? 'short' : 'long'

        // trigger_price = 0 表示市价单，传 null 让 SignalCard 自行处理
        const triggerPrice = sig.trigger_price > 0 ? sig.trigger_price : null

        return (
          <SignalCard
            key={sig.id}
            id={sig.id}
            action={sig.action}
            direction={direction}
            symbol={sig.symbol}
            triggerPrice={triggerPrice}
            triggerTime={new Date(sig.trigger_time).toLocaleString('zh-CN')}
            urgency={sig.urgency}
            isRead={sig.is_read}
            strategyName={strategyName}
            confidence={sig.confidence}
            status={sig.status}
          />
        )
      })}
      <button
        onClick={onViewAll}
        className="w-full text-center py-3 text-sm hover:text-[var(--gr-red)] transition-colors"
        style={{ color: 'var(--gr-blue)' }}
      >
        查看全部信号 →
      </button>
    </div>
  )
}

/* ---------- Skeleton ---------- */

function HeaderSkeleton() {
  return (
    <div className="space-y-3">
      <div className="flex items-start justify-between">
        <div className="space-y-2 flex-1">
          <div className="h-3 skeleton w-20" />
          <div className="h-5 skeleton w-[60%]" />
        </div>
        <div className="flex gap-2">
          <div className="h-8 skeleton w-20" />
          <div className="h-8 skeleton w-16" />
        </div>
      </div>
      <div className="flex gap-2">
        <div className="h-5 skeleton w-16" />
        <div className="h-5 skeleton w-16" />
        <div className="h-5 skeleton w-24" />
      </div>
      <div className="h-3 skeleton w-full" />
      <div className="h-3 skeleton w-[80%]" />
      <div className="flex gap-2">
        <div className="h-5 skeleton w-16" />
        <div className="h-5 skeleton w-16" />
      </div>
    </div>
  )
}