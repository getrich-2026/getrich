import { useState } from 'react'

interface StrategyActionBarProps {
  isSubscribed: boolean
  monthlyPrice: number
  yearlyPrice: number
  expireDate?: string
  onSubscribe?: () => void
}

export function StrategyActionBar({
  isSubscribed,
  monthlyPrice,
  yearlyPrice,
  expireDate,
  onSubscribe,
}: StrategyActionBarProps) {
  return (
    <div
      className="fixed bottom-0 left-0 right-0 z-50 flex items-center justify-center"
      style={{
        paddingLeft: 56,
        background: 'rgba(255,255,255,0.85)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        borderTop: '1px solid var(--gr-border-light)',
        boxShadow: '0 -4px 20px rgba(0,0,0,0.08)',
      }}
    >
      <div className="max-w-[1120px] w-full mx-auto px-6 py-3 flex items-center justify-between">
        {isSubscribed ? (
          <>
            <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>
              已订阅至 {expireDate} · 自动续费已开启
            </span>
            <button
              className="px-4 py-2 rounded-md text-xs font-medium transition-colors duration-150 hover:bg-[var(--gr-card-hover)]"
              style={{
                border: '1px solid var(--gr-border)',
                color: 'var(--gr-text-secondary)',
                background: 'transparent',
              }}
            >
              管理订阅
            </button>
          </>
        ) : (
          <>
            <div className="flex items-center gap-6">
              <div className="flex flex-col">
                <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>
                  月订阅
                </span>
                <span className="text-sm font-semibold" style={{ color: 'var(--gr-text)' }}>
                  ¥{monthlyPrice}/月
                </span>
              </div>
              <div className="flex flex-col">
                <div className="flex items-center gap-2">
                  <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>
                    年订阅
                  </span>
                  <Tag variant="green" size="default">
                    省¥{monthlyPrice * 12 - yearlyPrice}
                  </Tag>
                </div>
                <span
                  className="text-base font-semibold tabular"
                  style={{ color: 'var(--gr-text)' }}
                >
                  ¥{yearlyPrice}/年
                </span>
              </div>
            </div>
            <button
              onClick={onSubscribe}
              className="px-8 py-2.5 rounded-md text-sm font-semibold text-white transition-all duration-150 hover:opacity-90"
              style={{ background: 'var(--gr-red)' }}
            >
              立即订阅
            </button>
          </>
        )}
      </div>
    </div>
  )
}

import Tag from './Tag'

interface SignalActionBarProps {
  isExecuted: boolean
  triggerPrice?: number
  executedPrice?: number
  executedAt?: string
  slippage?: number
  onExecute?: (price: number, note: string) => void
}

export function SignalActionBar({
  isExecuted,
  triggerPrice,
  executedPrice,
  executedAt,
  slippage,
  onExecute,
}: SignalActionBarProps) {
  const [price, setPrice] = useState(triggerPrice?.toString() || '')
  const [note, setNote] = useState('')

  return (
    <div
      className="fixed bottom-0 left-0 right-0 z-50 flex items-center justify-center"
      style={{
        paddingLeft: 56,
        background: 'rgba(255,255,255,0.85)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        borderTop: '1px solid var(--gr-border-light)',
        boxShadow: '0 -4px 20px rgba(0,0,0,0.08)',
      }}
    >
      <div className="max-w-[1120px] w-full mx-auto px-6 py-3 flex items-center justify-between">
        {isExecuted ? (
          <div className="flex items-center gap-4">
            <Tag variant="green" size="lg">
              已执行 ✓
            </Tag>
            <span className="text-sm font-semibold tabular" style={{ color: 'var(--gr-text)' }}>
              @{executedPrice?.toFixed(2)}
            </span>
            {slippage !== undefined && (
              <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>
                滑点 {slippage > 0 ? '+' : ''}{slippage.toFixed(2)}
              </span>
            )}
            <span className="text-xs ml-auto" style={{ color: 'var(--gr-text-tertiary)' }}>
              {executedAt}
            </span>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-4">
              <button
                className="px-3 py-2 rounded-md text-xs font-medium transition-colors duration-150"
                style={{
                  border: '1px solid var(--gr-blue)',
                  color: 'var(--gr-blue)',
                  background: 'transparent',
                }}
              >
                标记已执行
              </button>
              <div className="flex items-center gap-2">
                <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>
                  执行价格
                </span>
                <input
                  type="text"
                  value={price}
                  onChange={(e) => setPrice(e.target.value)}
                  className="w-[120px] px-2 py-1.5 rounded-md text-right tabular text-sm font-medium outline-none focus:ring-1"
                  style={{
                    border: '1px solid var(--gr-border)',
                    color: 'var(--gr-text)',
                    background: 'var(--gr-bg)',
                  }}
                />
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>
                  备注
                </span>
                <input
                  type="text"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="可选"
                  className="w-[160px] px-2 py-1.5 rounded-md text-sm outline-none focus:ring-1"
                  style={{
                    border: '1px solid var(--gr-border)',
                    color: 'var(--gr-text)',
                    background: 'var(--gr-bg)',
                  }}
                />
              </div>
            </div>
            <button
              onClick={() => onExecute?.(Number(price), note)}
              className="px-6 py-2.5 rounded-md text-sm font-semibold text-white transition-all duration-150 hover:opacity-90"
              style={{ background: 'var(--gr-red)' }}
            >
              提交反馈
            </button>
          </>
        )}
      </div>
    </div>
  )
}
