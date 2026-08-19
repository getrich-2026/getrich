import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import Tag from '@/components/Tag'
import { SignalActionBar } from '@/components/BottomActionBar'
import { getSignalDetail } from '@/api/signal'

/* ---------- Page Component ---------- */

export default function SignalDetail() {
  const navigate = useNavigate()
  const { id } = useParams()

  // 各分块的加载态一律判 !s 而不是 isLoading —— isLoading 无法让 TS 收窄 s 的类型，
  // 判 !s 既能收窄又与「数据到达前显示骨架屏」的语义完全一致。
  const { data: s, isError } = useQuery({
    queryKey: ['signal', id],
    queryFn: () => getSignalDetail(id!),
    enabled: !!id,
  })

  // urgency → Tag variant / 显示文字映射
  const urgencyTag  = s?.urgency === 'critical' ? ('red' as const) : s?.urgency === 'high' ? ('orange' as const) : s?.urgency === 'low' ? ('gray' as const) : ('blue' as const)
  const urgencyText = s?.urgency === 'critical' ? '紧急' : s?.urgency === 'high' ? '高' : s?.urgency === 'low' ? '低' : '普通'

  // 目标/止损相对触发价的涨跌幅（%）
  const targetPct = s ? ((s.target_price   - s.trigger_price) / s.trigger_price * 100) : 0
  const stopPct   = s ? ((s.stop_loss_price - s.trigger_price) / s.trigger_price * 100) : 0

  // 技术指标在 market_snapshot.indicators 下，不是 market_snapshot 的直属字段
  const ind = s?.market_snapshot?.indicators

  if (isError) {
    return (
      <div className="flex items-center justify-center py-32 text-sm" style={{ color: 'var(--gr-text-tertiary)' }}>
        信号加载失败
      </div>
    )
  }

  return (
    <div className="pb-24">
      <div className="max-w-[1100px] mx-auto px-6 py-6">

        {/* ========== Section 1: Signal Header ========== */}
        <div className="mb-5">
          {!s ? (
            <HeaderSkeleton />
          ) : (
            <div className="fade-in">
              <button
                onClick={() => navigate('/market')}
                className="flex items-center gap-1 mb-3 transition-colors duration-150 hover:text-(--gr-text)"
                style={{ color: 'var(--gr-text-secondary)', fontSize: '13px' }}
              >
                <ArrowLeft size={14} />
                <span>信号流</span>
              </button>

              <div className="flex items-center gap-3 mb-2 flex-wrap">
                <h1 className="text-2xl font-bold" style={{ color: 'var(--gr-text)', letterSpacing: '-0.01em' }}>
                  <span style={{ color: 'var(--gr-green)', fontWeight: 700 }}>买入</span>
                  <span> 做多 </span>
                  <span>{s.symbol}</span>
                  <span className="text-sm font-normal ml-2" style={{ color: 'var(--gr-text-secondary)' }}>
                    （{s.symbol_name}）
                  </span>
                </h1>
                <Tag variant={urgencyTag} size="lg">{urgencyText}</Tag>
                <span className="text-sm font-medium tabular" style={{ color: 'var(--gr-text)' }}>
                  {Math.round(s.confidence * 100)}%
                </span>
              </div>

              <div className="flex items-center gap-2 mb-2 text-xs flex-wrap">
                <button
                  onClick={() => navigate(`/strategies/${s.strategy?.id}`)}
                  className="hover:underline transition-colors"
                  style={{ color: 'var(--gr-blue)' }}
                >
                  {s.strategy?.name}
                </button>
                <span style={{ color: 'var(--gr-text-tertiary)' }}>→</span>
                <span style={{ color: 'var(--gr-text-secondary)' }}>
                  {s.signal_type === 'entry' ? '入场信号' : s.signal_type === 'exit' ? '离场信号' : s.signal_type === 'adjust' ? '调仓信号' : '预警'}
                </span>
                <span style={{ color: 'var(--gr-text-tertiary)' }}>·</span>
                <span style={{ color: 'var(--gr-text-tertiary)' }}>{s.trigger_time}</span>
              </div>

              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full" style={{ background: s.status === 'active' ? 'var(--gr-green)' : 'var(--gr-text-tertiary)' }} />
                <span className="text-sm" style={{ color: 'var(--gr-text)' }}>
                  {s.status === 'active' ? '有效' : s.status === 'expired' ? '已过期' : '已取消'}
                </span>
                {s.expired_at && (
                  <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>（{s.expired_at} 过期）</span>
                )}
              </div>
            </div>
          )}
        </div>

        {/* ========== Section 2: Price Panel ========== */}
        <div className="rounded-xl card-shadow mb-5 overflow-hidden" style={{ background: 'var(--gr-card)' }}>
          {!s ? (
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
              {/* 显式标注元素类型：只有中间两项带 subColor */}
              {([
                { label: '触发价格', value: s.trigger_price.toFixed(2),   sub: null },
                { label: '目标价格', value: s.target_price.toFixed(2),    sub: `+${targetPct.toFixed(2)}%`, subColor: 'var(--gr-green)' },
                { label: '止损价格', value: s.stop_loss_price.toFixed(2), sub: `${stopPct.toFixed(2)}%`,   subColor: 'var(--gr-red)' },
                { label: '建议仓位', value: `${Math.round(s.position_pct * 100)}%`, sub: `${s.suggested_quantity}手` },
              ] as { label: string; value: string; sub: string | null; subColor?: string }[]).map((item, i) => (
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
          {!s ? (
            <ReasonSkeleton />
          ) : (
            <div className="fade-in">
              <h2 className="text-lg font-semibold mb-3" style={{ color: 'var(--gr-text)' }}>触发原因</h2>
              <p className="text-sm mb-5" style={{ color: 'var(--gr-text)', lineHeight: 1.6 }}>{s.reason}</p>

              <div className="grid grid-cols-4 gap-3 mb-4">
                {[
                  { label: '当前价差', value: s.reason_detail?.spread_current?.toFixed(1) },
                  { label: '历史均值', value: s.reason_detail?.spread_mean?.toFixed(1) },
                  // TODO(后端): reason_detail 目前只返回 spread_current / spread_mean /
                  // z_score / trigger_rule，没有 spread_std，补齐后改回真实值
                  { label: '标准差',   value: undefined },
                  { label: 'Z-Score', value: s.reason_detail?.z_score?.toFixed(1) },
                ].map((item) => (
                  <div key={item.label} className="rounded-lg p-3 text-center" style={{ background: 'var(--gr-bg)' }}>
                    <div className="text-[10px] font-medium uppercase tracking-wide mb-1" style={{ color: 'var(--gr-text-tertiary)', letterSpacing: '0.05em' }}>
                      {item.label}
                    </div>
                    <div className="text-base font-bold tabular" style={{ color: 'var(--gr-text)' }}>
                      {item.value ?? '-'}
                    </div>
                  </div>
                ))}
              </div>

              <div className="rounded-lg p-4 flex items-center gap-3" style={{ background: 'var(--gr-blue-light)' }}>
                <span className="text-[10px] font-semibold uppercase tracking-wide shrink-0" style={{ color: 'var(--gr-blue)', letterSpacing: '0.05em' }}>触发规则</span>
                <div className="h-4 w-px" style={{ background: 'var(--gr-blue)', opacity: 0.3 }} />
                <span className="text-sm font-medium" style={{ color: 'var(--gr-blue)' }}>{s.reason_detail?.trigger_rule}</span>
              </div>
            </div>
          )}
        </div>

        {/* ========== Section 4: Market Snapshot ========== */}
        <div className="rounded-xl p-5 mb-5 card-shadow overflow-hidden" style={{ background: 'var(--gr-card)' }}>
          {!s ? (
            <SnapshotSkeleton />
          ) : (
            <div className="fade-in">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold" style={{ color: 'var(--gr-text)' }}>触发时刻行情</h2>
                <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>{s.trigger_time}</span>
              </div>

              <div className="grid grid-cols-4 gap-3 mb-4">
                {/* 显式标注元素类型：只有「收盘」那项带 bg */}
                {([
                  { label: '开盘',       value: s.market_snapshot?.open?.toFixed(2),  color: 'var(--gr-text)' },
                  { label: '最高',       value: s.market_snapshot?.high?.toFixed(2),  color: 'var(--gr-red)' },
                  { label: '最低',       value: s.market_snapshot?.low?.toFixed(2),   color: 'var(--gr-green)' },
                  { label: '收盘（触发价）', value: s.market_snapshot?.close?.toFixed(2), color: 'var(--gr-red)', bg: '#FEF2F2' },
                ] as { label: string; value?: string; color: string; bg?: string }[]).map((item) => (
                  <div key={item.label} className="text-center rounded-lg py-4 px-2" style={{ background: item.bg || 'var(--gr-bg)' }}>
                    <div className="text-[10px] font-medium uppercase tracking-wide mb-1.5" style={{ color: 'var(--gr-text-tertiary)', letterSpacing: '0.05em' }}>{item.label}</div>
                    <div className="text-xl font-bold tabular" style={{ color: item.color }}>{item.value ?? '-'}</div>
                  </div>
                ))}
              </div>

              <div className="grid grid-cols-3 gap-3 mb-4">
                <div className="rounded-lg p-4 text-center" style={{ background: 'var(--gr-bg)' }}>
                  <div className="text-[10px] font-medium uppercase tracking-wide mb-1.5" style={{ color: 'var(--gr-text-tertiary)', letterSpacing: '0.05em' }}>成交量</div>
                  <div className="text-xl font-bold tabular" style={{ color: 'var(--gr-text)' }}>{s.market_snapshot?.volume?.toLocaleString()}<span className="text-xs font-normal ml-1" style={{ color: 'var(--gr-text-tertiary)' }}>手</span></div>
                </div>
                <div className="rounded-lg p-4 text-center" style={{ background: 'var(--gr-bg)' }}>
                  <div className="text-[10px] font-medium uppercase tracking-wide mb-1.5" style={{ color: 'var(--gr-text-tertiary)', letterSpacing: '0.05em' }}>持仓量</div>
                  <div className="text-xl font-bold tabular" style={{ color: 'var(--gr-text)' }}>{s.market_snapshot?.open_interest?.toLocaleString()}<span className="text-xs font-normal ml-1" style={{ color: 'var(--gr-text-tertiary)' }}>手</span></div>
                </div>
                <div className="rounded-lg p-4 text-center" style={{ background: 'var(--gr-bg)' }}>
                  <div className="text-[10px] font-medium uppercase tracking-wide mb-1.5" style={{ color: 'var(--gr-text-tertiary)', letterSpacing: '0.05em' }}>基差</div>
                  {/* TODO(后端): market_snapshot 没有 basis 字段，补齐后接真实值并恢复涨跌配色 */}
                  <div className="text-xl font-bold tabular" style={{ color: 'var(--gr-text)' }}>-</div>
                </div>
              </div>

              <div className="grid grid-cols-4 gap-3">
                {[
                  { label: 'MA5',  value: ind?.ma5?.toFixed(2),    trend: (ind?.ma5 ?? 0) > (ind?.ma20 ?? 0) ? 'up' : 'down' },
                  { label: 'MA20', value: ind?.ma20?.toFixed(2),   trend: 'neutral' },
                  { label: 'RSI',  value: ind?.rsi_14?.toFixed(1), trend: (ind?.rsi_14 ?? 0) > 70 ? 'up' : (ind?.rsi_14 ?? 0) < 30 ? 'down' : 'neutral' },
                  { label: 'ATR',  value: ind?.atr_14?.toFixed(1), trend: 'neutral' },
                ].map((item) => (
                  <div key={item.label} className="rounded-lg p-3 text-center" style={{ background: 'var(--gr-bg)' }}>
                    <div className="text-[10px] font-medium uppercase tracking-wide mb-1" style={{ color: 'var(--gr-text-tertiary)', letterSpacing: '0.05em' }}>{item.label}</div>
                    <div className="flex items-center justify-center gap-1">
                      <span className="text-base font-bold tabular" style={{ color: 'var(--gr-text)' }}>{item.value ?? '-'}</span>
                      {item.trend === 'up'   && <span className="text-xs" style={{ color: 'var(--gr-red)' }}>&#9650;</span>}
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
          {!s ? (
            <PerfSkeleton />
          ) : (
            <div className="fade-in">
              <h2 className="text-lg font-semibold mb-4" style={{ color: 'var(--gr-text)' }}>历史同类信号表现</h2>

              <div className="flex items-center gap-6 mb-5">
                <div className="shrink-0 relative" style={{ width: 140, height: 80 }}>
                  <svg viewBox="0 0 140 80" className="w-full h-full">
                    <path d="M 10 70 A 60 60 0 0 1 130 70" fill="none" stroke="#E5E7EB" strokeWidth="10" strokeLinecap="round" />
                    <path
                      d="M 10 70 A 60 60 0 0 1 130 70"
                      fill="none"
                      stroke="#22C55E"
                      strokeWidth="10"
                      strokeLinecap="round"
                      strokeDasharray={`${s.historical_performance?.win_rate * 188} 188`}
                    />
                  </svg>
                  <div className="absolute bottom-0 left-0 right-0 text-center">
                    <div className="text-2xl font-bold tabular" style={{ color: 'var(--gr-green)' }}>{((s.historical_performance?.win_rate ?? 0) * 100).toFixed(1)}%</div>
                    <div className="text-[10px] font-medium uppercase tracking-wide" style={{ color: 'var(--gr-text-tertiary)', letterSpacing: '0.05em' }}>胜率</div>
                  </div>
                </div>

                <div className="h-16 w-px" style={{ background: 'var(--gr-border-light)' }} />

                <div className="flex-1">
                  <div className="text-[10px] font-medium uppercase tracking-wide mb-1" style={{ color: 'var(--gr-text-tertiary)', letterSpacing: '0.05em' }}>平均收益</div>
                  <div className="text-3xl font-bold tabular" style={{ color: 'var(--gr-green)' }}>+{((s.historical_performance?.avg_return ?? 0) * 100).toFixed(2)}%</div>
                  <div className="text-xs mt-1" style={{ color: 'var(--gr-text-secondary)' }}>基于 {s.historical_performance?.similar_signals_count} 次相似信号统计</div>
                </div>

                <div className="shrink-0 text-right">
                  <div className="text-[10px] font-medium uppercase tracking-wide mb-1" style={{ color: 'var(--gr-text-tertiary)', letterSpacing: '0.05em' }}>平均持有</div>
                  <div className="text-2xl font-bold tabular" style={{ color: 'var(--gr-text)' }}>{s.historical_performance?.avg_holding_days}<span className="text-sm font-normal" style={{ color: 'var(--gr-text-tertiary)' }}>天</span></div>
                </div>
              </div>

              {/* TODO(后端): historical_performance 只返回 similar_signals_count / win_rate /
                  avg_return / avg_holding_days，没有 best_return / worst_return。
                  原设计在这里有一组「最佳收益 / 最差收益」进度条，后端补齐字段后恢复。 */}
            </div>
          )}
        </div>

        {/* ========== Section 6: Related Signals ==========
            TODO(后端): /v1/signals/{id} 不返回 related_signals，这一整块原本恒为空列表。
            后端补齐该字段（或改由 /v1/signals?strategy_id= 拉取）后恢复，
            渲染用的 SignalCard 组件仍在。 */}
      </div>

      <SignalActionBar isExecuted={s?.user_state?.is_executed ?? false} triggerPrice={s?.trigger_price} />
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
      <div className="grid grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-20 skeleton rounded-lg" />
        ))}
      </div>
      <div className="grid grid-cols-3 gap-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-20 skeleton rounded-lg" />
        ))}
      </div>
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