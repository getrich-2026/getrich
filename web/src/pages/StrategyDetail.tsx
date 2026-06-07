import { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Share2 } from 'lucide-react'
import Tag from '@/components/Tag'
import MetricCard from '@/components/MetricCard'
import EquityChart from '@/components/EquityChart'
import MonthlyHeatmap from '@/components/MonthlyHeatmap'
import SignalCard from '@/components/SignalCard'
import { StrategyActionBar } from '@/components/BottomActionBar'

/* ---------- Mock Data ---------- */

interface StrategyData {
  id: string
  name: string
  description: string
  category: string
  riskLevel: string
  assetClass: string
  updatedAt: string
  tags: string[]
  isSubscribed: boolean
  subscriptionPrice: { monthly: number; yearly: number }
  expireDate: string
  creator: { name: string; bio: string }
  performance: {
    annualizedReturn: number
    maxDrawdown: number
    sharpeRatio: number
    winRate: number
    profitFactor: number
    ytdReturn: number
  }
  recentSignals: Array<{
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
  }>
}

const mockStrategy: StrategyData = {
  id: 'STR_FUT_001',
  name: '股指期货跨期套利',
  description: '基于 IF/IH/IC 不同月份合约价差的统计套利策略，利用价差偏离历史均值时的回归特性进行交易。',
  category: '套利策略',
  riskLevel: 'medium',
  assetClass: '期货',
  updatedAt: '2026-04-15 08:00',
  tags: ['股指期货', '跨期套利', '统计套利'],
  isSubscribed: false,
  subscriptionPrice: { monthly: 99, yearly: 899 },
  expireDate: '2026-12-31',
  creator: {
    name: 'MillerQuant 研究团队',
    bio: '专注期货量化策略研究，团队核心成员均有 5 年以上实盘经验',
  },
  performance: {
    annualizedReturn: 0.171,
    maxDrawdown: -0.119,
    sharpeRatio: 1.85,
    winRate: 0.625,
    profitFactor: 1.78,
    ytdReturn: 0.0812,
  },
  recentSignals: [
    {
      id: 'SIG_20260414_003',
      action: 'buy',
      direction: 'long',
      symbol: 'IF2506',
      triggerPrice: 3650.00,
      triggerTime: '04-14 14:30',
      urgency: 'high',
      isRead: false,
      strategyName: '股指期货跨期套利',
      confidence: 0.85,
    },
    {
      id: 'SIG_20260414_002',
      action: 'sell',
      direction: 'long',
      symbol: 'IF2506',
      triggerPrice: 3680.00,
      triggerTime: '04-14 10:15',
      urgency: 'normal',
      isRead: true,
      strategyName: '股指期货跨期套利',
      confidence: 0.72,
    },
    {
      id: 'SIG_20260413_001',
      action: 'buy',
      direction: 'long',
      symbol: 'IF2509',
      triggerPrice: 3630.00,
      triggerTime: '04-13 09:35',
      urgency: 'normal',
      isRead: true,
      strategyName: '股指期货跨期套利',
      confidence: 0.68,
    },
  ],
}

const tabs = ['策略说明', '回测报告', '历史交易', '最近信号']

/* ---------- Page Component ---------- */

export default function StrategyDetail() {
  const navigate = useNavigate()
  const { id } = useParams()
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState(0)

  // TODO: Replace with API call
  // useEffect(() => { fetch(`/api/strategies/${id}`).then(r => r.json()).then(data => { setStrategy(data); setLoading(false) }) }, [id])
  useEffect(() => {
    console.log('Loading strategy:', id)
    const t = setTimeout(() => setLoading(false), 800)
    return () => clearTimeout(t)
  }, [id])

  const s = mockStrategy
  const perf = s.performance

  return (
    <div className="pb-24">
      <div className="max-w-[1100px] mx-auto px-6 py-6">
        {/* ========== Section 1: Header ========== */}
        <div className="mb-5">
          {loading ? (
            <HeaderSkeleton />
          ) : (
            <div className="fade-in">
              {/* Back + Title row */}
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
                  <h1 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--gr-text)', letterSpacing: '-0.01em' }}>
                    {s.name}
                  </h1>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  {s.isSubscribed ? (
                    <>
                      <Tag variant="green" size="lg">已订阅</Tag>
                      <button className="p-2 rounded-md hover:bg-[var(--gr-bg)] transition-colors" style={{ color: 'var(--gr-text-secondary)' }}>
                        <Share2 size={16} />
                      </button>
                    </>
                  ) : (
                    <>
                      <button className="px-4 py-2 rounded-md text-sm font-semibold text-white" style={{ background: 'var(--gr-red)' }}>
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
                <Tag variant="blue">{s.category}</Tag>
                <span style={{ color: 'var(--gr-text-tertiary)' }}>·</span>
                <Tag variant="orange">{s.riskLevel === 'medium' ? '中风险' : s.riskLevel}</Tag>
                <span style={{ color: 'var(--gr-text-tertiary)' }}>·</span>
                <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>{s.assetClass}</span>
                <span style={{ color: 'var(--gr-text-tertiary)' }}>·</span>
                <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>更新于 {s.updatedAt}</span>
              </div>

              {/* Description */}
              <p className="text-sm mb-3" style={{ color: 'var(--gr-text-secondary)', lineHeight: 1.6 }}>
                {s.description}
              </p>

              {/* Tags */}
              <div className="flex gap-2">
                {s.tags.map((tag) => (
                  <Tag key={tag} variant="blue">{tag}</Tag>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ========== Section 2: 6-Grid Metrics ========== */}
        <div className="grid grid-cols-3 gap-3 mb-5">
          <MetricCard label="年化收益" value={`+${(perf.annualizedReturn * 100).toFixed(2)}%`} color="green" tooltip="策略自运行以来的年化复合收益率" delay={0} isLoading={loading} />
          <MetricCard label="最大回撤" value={`${(perf.maxDrawdown * 100).toFixed(2)}%`} color="red" tooltip="策略历史上从高点到低点的最大亏损幅度" delay={50} isLoading={loading} />
          <MetricCard label="夏普比率" value={perf.sharpeRatio.toFixed(2)} color={perf.sharpeRatio >= 1 ? 'green' : 'neutral'} tooltip="每单位风险所获得的超额回报" delay={100} isLoading={loading} />
          <MetricCard label="胜率" value={`${(perf.winRate * 100).toFixed(2)}%`} color={perf.winRate >= 0.5 ? 'green' : 'red'} tooltip="盈利交易次数占总交易次数的比例" delay={150} isLoading={loading} />
          <MetricCard label="盈亏比" value={perf.profitFactor.toFixed(2)} color={perf.profitFactor >= 1 ? 'green' : 'red'} tooltip="平均盈利金额与平均亏损金额的比值" delay={200} isLoading={loading} />
          <MetricCard label="今年收益" value={`+${(perf.ytdReturn * 100).toFixed(2)}%`} color="green" tooltip="本日历年度以来的累计收益率" delay={250} isLoading={loading} />
        </div>

        {/* ========== Section 3: Equity Curve ========== */}
        <div className="rounded-xl p-5 mb-5 card-shadow" style={{ background: 'var(--gr-card)' }}>
          <EquityChart isLoading={loading} />
        </div>

        {/* ========== Section 4: Monthly Heatmap ========== */}
        <div className="rounded-xl p-5 mb-5 card-shadow" style={{ background: 'var(--gr-card)' }}>
          <MonthlyHeatmap isLoading={loading} />
        </div>

        {/* ========== Section 5: Tabs ========== */}
        <div className="rounded-xl overflow-hidden card-shadow" style={{ background: 'var(--gr-card)' }}>
          {/* Tab bar */}
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
                  <div className="absolute bottom-0 left-0 right-0 h-0.5" style={{ background: 'var(--gr-red)' }} />
                )}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="p-5">
            {loading ? (
              <div className="space-y-3">
                <div className="h-4 skeleton w-full" />
                <div className="h-4 skeleton w-[90%]" />
                <div className="h-4 skeleton w-[70%]" />
              </div>
            ) : (
              <div className="fade-in">
                {activeTab === 0 && <StrategyDescTab />}
                {activeTab === 1 && <BacktestTab />}
                {activeTab === 2 && (
                  <div className="text-center py-8" style={{ color: 'var(--gr-text-tertiary)' }}>
                    历史交易记录功能开发中...
                  </div>
                )}
                {activeTab === 3 && (
                  <div>
                    {s.recentSignals.map((sig) => (
                      <SignalCard key={sig.id} {...sig} />
                    ))}
                    <button
                      onClick={() => navigate('/signals')}
                      className="w-full text-center py-3 text-sm hover:text-[var(--gr-red)] transition-colors"
                      style={{ color: 'var(--gr-blue)' }}
                    >
                      查看全部信号 →
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Bottom Action Bar */}
      <StrategyActionBar
        isSubscribed={s.isSubscribed}
        monthlyPrice={s.subscriptionPrice.monthly}
        yearlyPrice={s.subscriptionPrice.yearly}
        expireDate={s.expireDate}
      />
    </div>
  )
}

/* ---------- Tab Content Components ---------- */

function StrategyDescTab() {
  return (
    <div>
      <div className="text-sm space-y-3" style={{ color: 'var(--gr-text-secondary)', lineHeight: 1.7 }}>
        <p>
          本策略基于股指期货不同月份合约之间的价差进行统计套利。当价差偏离历史均值达到一定阈值时，
          策略会自动建立反向头寸，等待价差回归均值后平仓获利。
        </p>
        <p>
          策略主要交易 IF（沪深300）、IH（上证50）和 IC（中证500）三大股指期货的当月与次月合约组合。
          通过动态监测价差序列的均值回归特性，结合持仓量和波动率等辅助指标，提高开仓信号的可靠性。
        </p>
        <p>
          <strong style={{ color: 'var(--gr-text)' }}>适用场景：</strong>
          适合震荡行情和趋势不明显的市场环境，在单边行情中可能表现不佳。
        </p>
        <p>
          <strong style={{ color: 'var(--gr-text)' }}>风险说明：</strong>
          价差可能长期偏离均值而不回归，存在策略失效风险。建议控制单策略仓位不超过总资金的 20%。
        </p>
      </div>

      <h3 className="text-sm font-medium mt-6 mb-3" style={{ color: 'var(--gr-text)' }}>策略配置</h3>
      <div className="rounded-lg overflow-hidden" style={{ border: '1px solid var(--gr-border-light)' }}>
        {[
          ['交易标的', 'IF/IH/IC 当月 & 次月合约'],
          ['再平衡频率', '日内'],
          ['业绩基准', '中证500指数'],
          ['初始资金', '¥1,000,000'],
          ['滑点', '1 tick'],
          ['手续费', '万分之 0.23'],
        ].map(([label, value], i, arr) => (
          <div
            key={label}
            className="flex items-center px-4 h-10"
            style={{
              background: i % 2 === 0 ? 'var(--gr-bg)' : 'var(--gr-card)',
              borderBottom: i < arr.length - 1 ? '1px solid var(--gr-border-light)' : 'none',
            }}
          >
            <span className="text-xs w-28" style={{ color: 'var(--gr-text-tertiary)' }}>{label}</span>
            <span className="text-sm" style={{ color: 'var(--gr-text)' }}>{value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function BacktestTab() {
  const summaryItems: Array<{ label: string; value: string; color?: string }> = [
    { label: '初始资金', value: '¥1,000,000' },
    { label: '最终资金', value: '¥1,561,000' },
    { label: '总收益率', value: '+56.1%', color: 'var(--gr-green)' },
    { label: '回测区间', value: '2020.01-2026.04' },
  ]

  return (
    <div>
      <div className="grid grid-cols-4 gap-4 mb-6">
        {summaryItems.map((item) => (
          <div key={item.label} className="text-center">
            <div className="text-xs mb-1" style={{ color: 'var(--gr-text-tertiary)' }}>{item.label}</div>
            <div className="text-lg font-semibold tabular" style={{ color: item.color || 'var(--gr-text)' }}>
              {item.value}
            </div>
          </div>
        ))}
      </div>

      <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--gr-text)' }}>年度表现</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr style={{ background: 'var(--gr-bg)' }}>
              {['年份', '收益率', '最大回撤', '夏普比率', '交易次数'].map((h) => (
                <th key={h} className="text-left px-3 py-2 text-xs font-medium" style={{ color: 'var(--gr-text-tertiary)' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[
              [2020, 0.142, -0.089, 1.62, 24],
              [2021, 0.185, -0.072, 2.15, 28],
              [2022, 0.098, -0.119, 1.23, 32],
              [2023, 0.165, -0.068, 1.95, 26],
              [2024, 0.168, -0.075, 1.88, 24],
              [2025, 0.175, -0.062, 2.08, 22],
            ].map(([year, ret, dd, sharpe, trades]) => (
              <tr
                key={year as number}
                className="hover:bg-[#F9FAFB] transition-colors duration-150"
                style={{ borderBottom: '1px solid var(--gr-border-light)' }}
              >
                <td className="px-3 py-2.5" style={{ color: 'var(--gr-text)' }}>{year as number}</td>
                <td className="px-3 py-2.5 font-medium tabular" style={{ color: (ret as number) >= 0 ? 'var(--gr-green)' : 'var(--gr-red)' }}>
                  {(ret as number) >= 0 ? '+' : ''}{((ret as number) * 100).toFixed(1)}%
                </td>
                <td className="px-3 py-2.5 tabular" style={{ color: 'var(--gr-red)' }}>{((dd as number) * 100).toFixed(1)}%</td>
                <td className="px-3 py-2.5 tabular" style={{ color: 'var(--gr-text)' }}>{(sharpe as number).toFixed(2)}</td>
                <td className="px-3 py-2.5 tabular" style={{ color: 'var(--gr-text)' }}>{trades as number}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
        <div className="h-5 skeleton w-16" />
      </div>
    </div>
  )
}
