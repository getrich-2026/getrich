import { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import Tag from '@/components/Tag'
import SignalCard from '@/components/SignalCard'
import { SignalActionBar } from '@/components/BottomActionBar'

/* ---------- Mock Data ---------- */

const mockSignal = {
  id: 'SIG_20260415_001',
  strategy: {
    id: 'STR_FUT_001',
    name: '股指期货跨期套利',
    category: '套利策略',
    riskLevel: 'medium',
  },
  signalType: 'entry',
  action: 'buy',
  direction: 'long',
  symbol: 'IF2506',
  symbolName: '沪深300股指期货2506',
  triggerPrice: 3650.00,
  targetPrice: 3700.00,
  stopLossPrice: 3620.00,
  suggestedQuantity: 1,
  positionPct: 0.15,
  confidence: 0.85,
  urgency: 'high',
  reason: 'IF 当月-次月价差偏离 2σ，触发均值回归开仓',
  reasonDetail: {
    spreadCurrent: 12.4,
    spreadMean: 5.2,
    spreadStd: 3.6,
    zScore: 2.0,
    triggerRule: 'z_score > 2.0 且持仓量放大',
  },
  triggerTime: '2026-04-15 09:31',
  status: 'active',
  expiredAt: '2026-04-15 15:00',
  marketSnapshot: {
    open: 3645.00,
    high: 3658.00,
    low: 3640.00,
    close: 3650.00,
    volume: 25680,
    openInterest: 124500,
    ma5: 3642.00,
    ma20: 3618.00,
    rsi14: 62.3,
    atr14: 35.6,
    basis: -8.2,
  },
  historicalPerformance: {
    similarSignalsCount: 23,
    winRate: 0.7391,
    avgReturn: 0.0185,
    avgHoldingDays: 2.8,
    bestReturn: 0.0420,
    worstReturn: -0.0180,
  },
  relatedSignals: [
    {
      id: 'SIG_20260410_001',
      action: 'buy',
      direction: 'long',
      symbol: 'IF2506',
      triggerPrice: 3620.00,
      triggerTime: '04-10 09:35',
      urgency: 'normal',
      isRead: true,
      strategyName: '股指期货跨期套利',
      confidence: 0.78,
      result: { returnPct: 0.0166, status: 'closed_profit' },
    },
    {
      id: 'SIG_20260408_002',
      action: 'buy',
      direction: 'long',
      symbol: 'IF2506',
      triggerPrice: 3595.00,
      triggerTime: '04-08 09:40',
      urgency: 'normal',
      isRead: true,
      strategyName: '股指期货跨期套利',
      confidence: 0.82,
      result: { returnPct: 0.0089, status: 'closed_profit' },
    },
    {
      id: 'SIG_20260403_001',
      action: 'buy',
      direction: 'long',
      symbol: 'IF2506',
      triggerPrice: 3580.00,
      triggerTime: '04-03 09:32',
      urgency: 'high',
      isRead: true,
      strategyName: '股指期货跨期套利',
      confidence: 0.91,
      result: { returnPct: -0.0056, status: 'closed_loss' },
    },
  ],
  isExecuted: false,
}

/* ---------- Page Component ---------- */

interface PriceMetricItem {
  label: string
  value: string
  sub?: string | null
  subColor?: string
}

interface OhlcItem {
  label: string
  value: string
  color: string
  bg?: string
}

export default function SignalDetail() {
  const navigate = useNavigate()
  const { id } = useParams()
  const [loading, setLoading] = useState(true)

  // TODO: Replace with API call
  useEffect(() => {
    console.log('Loading signal:', id)
    const t = setTimeout(() => setLoading(false), 800)
    return () => clearTimeout(t)
  }, [id])

  const s = mockSignal
  const urgencyTag = s.urgency === 'critical' ? ('red' as const) : s.urgency === 'high' ? ('orange' as const) : s.urgency === 'low' ? ('gray' as const) : ('blue' as const)
  const urgencyText = s.urgency === 'critical' ? '紧急' : s.urgency === 'high' ? '高' : s.urgency === 'low' ? '低' : '普通'
  const targetPct = ((s.targetPrice - s.triggerPrice) / s.triggerPrice * 100)
  const stopPct = ((s.stopLossPrice - s.triggerPrice) / s.triggerPrice * 100)

  return (
    <div className="pb-24">
      <div className="max-w-[1100px] mx-auto px-6 py-6">
        {/* ========== Section 1: Signal Header ========== */}
        <div className="mb-5">
          {loading ? (
            <HeaderSkeleton />
          ) : (
            <div className="fade-in">
              <button
                onClick={() => navigate('/market')}
                className="flex items-center gap-1 mb-3 transition-colors duration-150 hover:text-[var(--gr-text)]"
                style={{ color: 'var(--gr-text-secondary)', fontSize: '13px' }}
              >
                <ArrowLeft size={14} />
                <span>信号流</span>
              </button>

              {/* Main title */}
              <div className="flex items-center gap-3 mb-2 flex-wrap">
                <h1 className="text-2xl font-bold" style={{ color: 'var(--gr-text)', letterSpacing: '-0.01em' }}>
                  <span style={{ color: 'var(--gr-green)', fontWeight: 700 }}>买入</span>
                  <span> 做多 </span>
                  <span>{s.symbol}</span>
                  <span className="text-sm font-normal ml-2" style={{ color: 'var(--gr-text-secondary)' }}>
                    （{s.symbolName}）
                  </span>
                </h1>
                <Tag variant={urgencyTag} size="lg">{urgencyText}</Tag>
                <span className="text-sm font-medium tabular" style={{ color: 'var(--gr-text)' }}>
                  {Math.round(s.confidence * 100)}%
                </span>
              </div>

              {/* Source line */}
              <div className="flex items-center gap-2 mb-2 text-xs flex-wrap">
                <button
                  onClick={() => navigate(`/strategies/${s.strategy.id}`)}
                  className="hover:underline transition-colors"
                  style={{ color: 'var(--gr-blue)' }}
                >
                  {s.strategy.name}
                </button>
                <span style={{ color: 'var(--gr-text-tertiary)' }}>→</span>
                <span style={{ color: 'var(--gr-text-secondary)' }}>
                  {s.signalType === 'entry' ? '入场信号' : s.signalType === 'exit' ? '离场信号' : s.signalType === 'adjust' ? '调仓信号' : '预警'}
                </span>
                <span style={{ color: 'var(--gr-text-tertiary)' }}>·</span>
                <span style={{ color: 'var(--gr-text-tertiary)' }}>{s.triggerTime}</span>
              </div>

              {/* Status */}
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full" style={{ background: s.status === 'active' ? 'var(--gr-green)' : 'var(--gr-text-tertiary)' }} />
                <span className="text-sm" style={{ color: 'var(--gr-text)' }}>
                  {s.status === 'active' ? '有效' : s.status === 'expired' ? '已过期' : '已取消'}
                </span>
                {s.expiredAt && (
                  <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>（{s.expiredAt} 过期）</span>
                )}
              </div>
            </div>
          )}
        </div>

        {/* ========== Section 2: Price Panel - unified card with dividers ========== */}
        <div className="rounded-xl card-shadow mb-5 overflow-hidden" style={{ background: 'var(--gr-card)' }}>
          {loading ? (
            <div className="grid grid-cols-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="p-5 text-center" style={{ borderRight: i < 3 ? '1px solid var(--gr-border-light)' : 'none' }}>
                  <div className="h-3 skeleton w-[50%] mx-auto mb-2" />
                  <div className="h-7 skeleton w-[70%] mx-auto" />
                </div>
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-4">
              {([
                { label: '触发价格', value: s.triggerPrice.toFixed(2), sub: null },
                { label: '目标价格', value: s.targetPrice.toFixed(2), sub: `+${targetPct.toFixed(2)}%`, subColor: 'var(--gr-green)' },
                { label: '止损价格', value: s.stopLossPrice.toFixed(2), sub: `${stopPct.toFixed(2)}%`, subColor: 'var(--gr-red)' },
                { label: '建议仓位', value: `${Math.round(s.positionPct * 100)}%`, sub: `${s.suggestedQuantity}手` },
              ] satisfies PriceMetricItem[]).map((item, i) => (
                <div
                  key={item.label}
                  className="p-5 text-center"
                  style={{ borderRight: i < 3 ? '1px solid var(--gr-border-light)' : 'none' }}
                >
                  <div className="text-[11px] font-medium uppercase tracking-wide mb-1.5" style={{ color: 'var(--gr-text-tertiary)', letterSpacing: '0.05em' }}>
                    {item.label}
                  </div>
                  <div className="tabular" style={{ fontSize: '26px', fontWeight: 800, lineHeight: 1.15, color: 'var(--gr-text)' }}>
                    {item.value}
                  </div>
                  {item.sub && (
                    <div className="text-xs mt-1 tabular font-medium" style={{ color: item.subColor || 'var(--gr-text-tertiary)' }}>
                      {item.sub}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ========== Section 3: Trigger Reason ========== */}
        <div className="rounded-xl p-5 mb-5 card-shadow overflow-hidden" style={{ background: 'var(--gr-card)' }}>
          {loading ? (
            <ReasonSkeleton />
          ) : (
            <div className="fade-in">
              <h2 className="text-lg font-semibold mb-3" style={{ color: 'var(--gr-text)' }}>触发原因</h2>
              <p className="text-sm mb-5" style={{ color: 'var(--gr-text)', lineHeight: 1.6 }}>{s.reason}</p>

              {/* Data grid - styled like mini metric cards */}
              <div className="grid grid-cols-4 gap-3 mb-4">
                {[
                  { label: '当前价差', value: s.reasonDetail.spreadCurrent.toFixed(1) },
                  { label: '历史均值', value: s.reasonDetail.spreadMean.toFixed(1) },
                  { label: '标准差', value: s.reasonDetail.spreadStd.toFixed(1) },
                  { label: 'Z-Score', value: s.reasonDetail.zScore.toFixed(1) },
                ].map((item) => (
                  <div
                    key={item.label}
                    className="rounded-lg p-3 text-center"
                    style={{ background: 'var(--gr-bg)' }}
                  >
                    <div className="text-[10px] font-medium uppercase tracking-wide mb-1" style={{ color: 'var(--gr-text-tertiary)', letterSpacing: '0.05em' }}>
                      {item.label}
                    </div>
                    <div className="text-base font-bold tabular" style={{ color: 'var(--gr-text)' }}>
                      {item.value}
                    </div>
                  </div>
                ))}
              </div>

              {/* Trigger Rule - styled as a rule bar */}
              <div className="rounded-lg p-4 flex items-center gap-3" style={{ background: 'var(--gr-blue-light)' }}>
                <span className="text-[10px] font-semibold uppercase tracking-wide flex-shrink-0" style={{ color: 'var(--gr-blue)', letterSpacing: '0.05em' }}>触发规则</span>
                <div className="h-4 w-px" style={{ background: 'var(--gr-blue)', opacity: 0.3 }} />
                <span className="text-sm font-medium" style={{ color: 'var(--gr-blue)' }}>{s.reasonDetail.triggerRule}</span>
              </div>
            </div>
          )}
        </div>

        {/* ========== Section 4: Market Snapshot ========== */}
        <div className="rounded-xl p-5 mb-5 card-shadow overflow-hidden" style={{ background: 'var(--gr-card)' }}>
          {loading ? (
            <SnapshotSkeleton />
          ) : (
            <div className="fade-in">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold" style={{ color: 'var(--gr-text)' }}>触发时刻行情</h2>
                <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>{s.triggerTime}</span>
              </div>

              {/* OHLC - 4 unified cards with bg */}
              <div className="grid grid-cols-4 gap-3 mb-4">
                {([
                  { label: '开盘', value: s.marketSnapshot.open.toFixed(2), color: 'var(--gr-text)' },
                  { label: '最高', value: s.marketSnapshot.high.toFixed(2), color: 'var(--gr-red)' },
                  { label: '最低', value: s.marketSnapshot.low.toFixed(2), color: 'var(--gr-green)' },
                  { label: '收盘（触发价）', value: s.marketSnapshot.close.toFixed(2), color: 'var(--gr-red)', bg: '#FEF2F2' },
                ] satisfies OhlcItem[]).map((item) => (
                  <div key={item.label} className="text-center rounded-lg py-4 px-2" style={{ background: item.bg || 'var(--gr-bg)' }}>
                    <div className="text-[10px] font-medium uppercase tracking-wide mb-1.5" style={{ color: 'var(--gr-text-tertiary)', letterSpacing: '0.05em' }}>{item.label}</div>
                    <div className="text-xl font-bold tabular" style={{ color: item.color }}>{item.value}</div>
                  </div>
                ))}
              </div>

              {/* Volume / OpenInterest / Basis - 3 mini cards */}
              <div className="grid grid-cols-3 gap-3 mb-4">
                <div className="rounded-lg p-4 text-center" style={{ background: 'var(--gr-bg)' }}>
                  <div className="text-[10px] font-medium uppercase tracking-wide mb-1.5" style={{ color: 'var(--gr-text-tertiary)', letterSpacing: '0.05em' }}>成交量</div>
                  <div className="text-xl font-bold tabular" style={{ color: 'var(--gr-text)' }}>{s.marketSnapshot.volume.toLocaleString()}<span className="text-xs font-normal ml-1" style={{ color: 'var(--gr-text-tertiary)' }}>手</span></div>
                </div>
                <div className="rounded-lg p-4 text-center" style={{ background: 'var(--gr-bg)' }}>
                  <div className="text-[10px] font-medium uppercase tracking-wide mb-1.5" style={{ color: 'var(--gr-text-tertiary)', letterSpacing: '0.05em' }}>持仓量</div>
                  <div className="text-xl font-bold tabular" style={{ color: 'var(--gr-text)' }}>{s.marketSnapshot.openInterest.toLocaleString()}<span className="text-xs font-normal ml-1" style={{ color: 'var(--gr-text-tertiary)' }}>手</span></div>
                </div>
                <div className="rounded-lg p-4 text-center" style={{ background: 'var(--gr-bg)' }}>
                  <div className="text-[10px] font-medium uppercase tracking-wide mb-1.5" style={{ color: 'var(--gr-text-tertiary)', letterSpacing: '0.05em' }}>基差</div>
                  <div className="text-xl font-bold tabular" style={{ color: s.marketSnapshot.basis >= 0 ? 'var(--gr-red)' : 'var(--gr-green)' }}>{s.marketSnapshot.basis >= 0 ? '+' : ''}{s.marketSnapshot.basis.toFixed(1)}</div>
                </div>
              </div>

              {/* Technical Indicators */}
              <div className="grid grid-cols-4 gap-3">
                {[
                  { label: 'MA5', value: s.marketSnapshot.ma5.toFixed(2), trend: s.marketSnapshot.ma5 > s.marketSnapshot.ma20 ? 'up' : 'down' },
                  { label: 'MA20', value: s.marketSnapshot.ma20.toFixed(2), trend: 'neutral' },
                  { label: 'RSI', value: s.marketSnapshot.rsi14.toFixed(1), trend: s.marketSnapshot.rsi14 > 70 ? 'up' : s.marketSnapshot.rsi14 < 30 ? 'down' : 'neutral' },
                  { label: 'ATR', value: s.marketSnapshot.atr14.toFixed(1), trend: 'neutral' },
                ].map((item) => (
                  <div key={item.label} className="rounded-lg p-3 text-center" style={{ background: 'var(--gr-bg)' }}>
                    <div className="text-[10px] font-medium uppercase tracking-wide mb-1" style={{ color: 'var(--gr-text-tertiary)', letterSpacing: '0.05em' }}>{item.label}</div>
                    <div className="flex items-center justify-center gap-1">
                      <span className="text-base font-bold tabular" style={{ color: 'var(--gr-text)' }}>{item.value}</span>
                      {item.trend === 'up' && <span className="text-xs" style={{ color: 'var(--gr-red)' }}>&#9650;</span>}
                      {item.trend === 'down' && <span className="text-xs" style={{ color: 'var(--gr-green)' }}>&#9660;</span>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ========== Section 5: Historical Performance ========== */}
        <div className="rounded-xl p-5 mb-5 card-shadow overflow-hidden" style={{ background: 'var(--gr-card)' }}>
          {loading ? (
            <PerfSkeleton />
          ) : (
            <div className="fade-in">
              <h2 className="text-lg font-semibold mb-4" style={{ color: 'var(--gr-text)' }}>历史同类信号表现</h2>

              {/* Top row: Win rate gauge + Avg return big number */}
              <div className="flex items-center gap-6 mb-5">
                {/* Win rate - semi-circle gauge */}
                <div className="flex-shrink-0 relative" style={{ width: 140, height: 80 }}>
                  <svg viewBox="0 0 140 80" className="w-full h-full">
                    {/* Background arc */}
                    <path d="M 10 70 A 60 60 0 0 1 130 70" fill="none" stroke="#E5E7EB" strokeWidth="10" strokeLinecap="round" />
                    {/* Value arc */}
                    <path
                      d="M 10 70 A 60 60 0 0 1 130 70"
                      fill="none"
                      stroke="#22C55E"
                      strokeWidth="10"
                      strokeLinecap="round"
                      strokeDasharray={`${s.historicalPerformance.winRate * 188} 188`}
                    />
                  </svg>
                  <div className="absolute bottom-0 left-0 right-0 text-center">
                    <div className="text-2xl font-bold tabular" style={{ color: 'var(--gr-green)' }}>{(s.historicalPerformance.winRate * 100).toFixed(1)}%</div>
                    <div className="text-[10px] font-medium uppercase tracking-wide" style={{ color: 'var(--gr-text-tertiary)', letterSpacing: '0.05em' }}>胜率</div>
                  </div>
                </div>

                {/* Divider */}
                <div className="h-16 w-px" style={{ background: 'var(--gr-border-light)' }} />

                {/* Avg return */}
                <div className="flex-1">
                  <div className="text-[10px] font-medium uppercase tracking-wide mb-1" style={{ color: 'var(--gr-text-tertiary)', letterSpacing: '0.05em' }}>平均收益</div>
                  <div className="text-3xl font-bold tabular" style={{ color: 'var(--gr-green)' }}>+{(s.historicalPerformance.avgReturn * 100).toFixed(2)}%</div>
                  <div className="text-xs mt-1" style={{ color: 'var(--gr-text-secondary)' }}>基于 {s.historicalPerformance.similarSignalsCount} 次相似信号统计</div>
                </div>

                {/* Avg holding */}
                <div className="flex-shrink-0 text-right">
                  <div className="text-[10px] font-medium uppercase tracking-wide mb-1" style={{ color: 'var(--gr-text-tertiary)', letterSpacing: '0.05em' }}>平均持有</div>
                  <div className="text-2xl font-bold tabular" style={{ color: 'var(--gr-text)' }}>{s.historicalPerformance.avgHoldingDays}<span className="text-sm font-normal" style={{ color: 'var(--gr-text-tertiary)' }}>天</span></div>
                </div>
              </div>

              <div className="h-px mb-4" style={{ background: 'var(--gr-border-light)' }} />

              {/* Bottom: Best vs Worst comparison bars */}
              <div className="space-y-3">
                {/* Best */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[10px] font-medium uppercase tracking-wide" style={{ color: 'var(--gr-text-tertiary)', letterSpacing: '0.05em' }}>最佳收益</span>
                    <span className="text-sm font-bold tabular" style={{ color: 'var(--gr-green)' }}>+{(s.historicalPerformance.bestReturn * 100).toFixed(2)}%</span>
                  </div>
                  <div className="h-2 rounded-full overflow-hidden" style={{ background: '#F0FDF4' }}>
                    <div className="h-full rounded-full" style={{ width: '100%', background: '#22C55E' }} />
                  </div>
                </div>

                {/* Worst */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[10px] font-medium uppercase tracking-wide" style={{ color: 'var(--gr-text-tertiary)', letterSpacing: '0.05em' }}>最差收益</span>
                    <span className="text-sm font-bold tabular" style={{ color: 'var(--gr-red)' }}>{(s.historicalPerformance.worstReturn * 100).toFixed(2)}%</span>
                  </div>
                  <div className="h-2 rounded-full overflow-hidden" style={{ background: '#FEF2F2' }}>
                    <div className="h-full rounded-full" style={{ width: `${Math.abs(s.historicalPerformance.worstReturn / s.historicalPerformance.bestReturn) * 100}%`, background: '#E8473F' }} />
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* ========== Section 6: Related Signals ========== */}
        <div className="rounded-xl p-5 card-shadow overflow-hidden" style={{ background: 'var(--gr-card)' }}>
          {loading ? (
            <div className="space-y-3">
              <div className="h-4 skeleton w-28" />
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="h-16 skeleton rounded-lg" />
              ))}
            </div>
          ) : (
            <div className="fade-in">
              <h2 className="text-lg font-semibold mb-3" style={{ color: 'var(--gr-text)' }}>同策略近期信号</h2>
              <div>
                {s.relatedSignals.map((sig) => (
                  <SignalCard key={sig.id} {...sig} />
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Bottom Action Bar */}
      <SignalActionBar isExecuted={s.isExecuted} triggerPrice={s.triggerPrice} />
    </div>
  )
}

/* ---------- Skeleton Components ---------- */

function HeaderSkeleton() {
  return (
    <div className="space-y-3">
      <div className="h-3 skeleton w-16" />
      <div className="flex items-center gap-3">
        <div className="h-6 skeleton w-[60%]" />
        <div className="h-6 skeleton w-12" />
        <div className="h-5 skeleton w-10" />
      </div>
      <div className="h-3 skeleton w-[50%]" />
      <div className="h-3 skeleton w-32" />
    </div>
  )
}

function ReasonSkeleton() {
  return (
    <div className="space-y-3">
      <div className="h-4 skeleton w-20" />
      <div className="h-3 skeleton w-full" />
      <div className="h-3 skeleton w-[80%]" />
      <div className="grid grid-cols-2 gap-3 mt-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i}>
            <div className="h-3 skeleton w-16 mb-1" />
            <div className="h-4 skeleton w-12" />
          </div>
        ))}
      </div>
    </div>
  )
}

function SnapshotSkeleton() {
  return (
    <div className="space-y-4">
      <div className="flex justify-between">
        <div className="h-5 skeleton w-24" />
        <div className="h-3 skeleton w-32" />
      </div>
      {/* OHLC */}
      <div className="grid grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-20 skeleton rounded-lg" />
        ))}
      </div>
      {/* Vol/OI/Basis */}
      <div className="grid grid-cols-3 gap-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-20 skeleton rounded-lg" />
        ))}
      </div>
      {/* Indicators */}
      <div className="grid grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-14 skeleton rounded-lg" />
        ))}
      </div>
    </div>
  )
}

function PerfSkeleton() {
  return (
    <div className="space-y-4">
      <div className="h-5 skeleton w-32" />
      <div className="flex items-center gap-6">
        <div className="h-20 skeleton w-36 rounded-lg" />
        <div className="h-16 w-px skeleton" />
        <div className="flex-1 space-y-2">
          <div className="h-3 skeleton w-16" />
          <div className="h-8 skeleton w-24" />
          <div className="h-3 skeleton w-40" />
        </div>
        <div className="space-y-2">
          <div className="h-3 skeleton w-12" />
          <div className="h-8 skeleton w-16" />
        </div>
      </div>
      <div className="h-px skeleton w-full" />
      <div className="space-y-3">
        <div className="h-3 skeleton w-full" />
        <div className="h-2 skeleton w-full rounded-full" />
        <div className="h-3 skeleton w-full" />
        <div className="h-2 skeleton w-[60%] rounded-full" />
      </div>
    </div>
  )
}
