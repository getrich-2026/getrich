import { useState, useEffect, useRef } from 'react'

interface MetricCardProps {
  label: string
  value: string | number
  color?: 'green' | 'red' | 'neutral'
  tooltip?: string
  delay?: number
  isLoading?: boolean
}

export default function MetricCard({
  label,
  value,
  color = 'neutral',
  tooltip,
  delay = 0,
  isLoading = false,
}: MetricCardProps) {
  const [show, setShow] = useState(false)
  const [showTip, setShowTip] = useState(false)
  const tipTimer = useRef<ReturnType<typeof setTimeout>>(null)

  useEffect(() => {
    const t = setTimeout(() => setShow(true), delay)
    return () => clearTimeout(t)
  }, [delay])

  const handleMouseEnter = () => {
    if (!tooltip) return
    tipTimer.current = setTimeout(() => setShowTip(true), 500)
  }
  const handleMouseLeave = () => {
    if (tipTimer.current) clearTimeout(tipTimer.current)
    setShowTip(false)
  }

  const bgMap = {
    green: 'linear-gradient(135deg, #F0FDF4 0%, #FFFFFF 100%)',
    red: 'linear-gradient(135deg, #FEF2F2 0%, #FFFFFF 100%)',
    neutral: '#FFFFFF',
  }
  const textMap = {
    green: '#22C55E',
    red: '#E8473F',
    neutral: '#1A1D24',
  }

  if (isLoading) {
    return (
      <div className="rounded-xl p-5 flex flex-col items-center gap-2 card-shadow">
        <div className="w-[50%] h-3 skeleton" />
        <div className="w-[70%] h-8 skeleton" />
      </div>
    )
  }

  return (
    <div
      className="rounded-xl p-5 flex flex-col items-center gap-1.5 relative cursor-default card-shadow-hover"
      style={{
        background: bgMap[color],
        opacity: show ? 1 : 0,
        transform: show ? 'translateY(0)' : 'translateY(8px)',
        transition: `opacity 200ms ease ${delay}ms, transform 200ms ease ${delay}ms, box-shadow 200ms ease`,
      }}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {/* Label */}
      <span className="text-[11px] font-medium uppercase tracking-wide" style={{ color: 'var(--gr-text-tertiary)', letterSpacing: '0.05em' }}>
        {label}
      </span>

      {/* Value - big and bold */}
      <span
        className="tabular"
        style={{ fontSize: '30px', fontWeight: 800, lineHeight: 1.15, color: textMap[color] }}
      >
        {value}
      </span>

      {/* Tooltip */}
      {tooltip && showTip && (
        <div
          className="absolute -top-2 left-1/2 -translate-x-1/2 -translate-y-full px-3 py-2 rounded-lg text-xs z-50 max-w-[200px] text-center"
          style={{ background: '#1A1D24', color: '#fff', boxShadow: '0 4px 12px rgba(0,0,0,0.15)' }}
        >
          {tooltip}
          <div className="absolute left-1/2 -translate-x-1/2 top-full w-0 h-0" style={{ borderLeft: '5px solid transparent', borderRight: '5px solid transparent', borderTop: '5px solid #1A1D24' }} />
        </div>
      )}
    </div>
  )
}
