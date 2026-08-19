import { useEffect, useRef, useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import * as echarts from 'echarts/core'
import type { EChartsCoreOption } from 'echarts/core'
import { HeatmapChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { getMonthlyReturns } from '@/api/strategies'

echarts.use([HeatmapChart, GridComponent, TooltipComponent, VisualMapComponent, CanvasRenderer])

interface MonthlyHeatmapProps {
  isLoading?: boolean
  strategyId?: string
}

// 热力图单元格：[月索引(12 表示年度列), 年索引, 百分比, 显示文本]
type HeatCell = [number, number, number | null, string]

// ECharts 把整个 data item 原样回传给 formatter，这里只声明用到的字段
interface HeatmapParam {
  data: { value: HeatCell }
}

const MONTH_LABELS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const X_AXIS_DATA  = [...MONTH_LABELS, 'Year']
const LEGEND_COLORS = ['#DC2626', '#F87171', '#FECACA', '#FFFFFF', '#BBF7D0', '#86EFAC', '#22C55E', '#16A34A']

function getColor(value: number | null): string {
  if (value === null) return '#F5F6F8'
  if (value >=  5)   return '#16A34A'
  if (value >=  3)   return '#22C55E'
  if (value >=  1.5) return '#86EFAC'
  if (value >=  0.5) return '#BBF7D0'
  if (value >= -0.5) return '#FFFFFF'
  if (value >= -1.5) return '#FECACA'
  if (value >= -3)   return '#F87171'
  return '#DC2626'
}

function getTextColor(value: number | null): string {
  if (value === null)              return '#9CA3AF'
  if (value >= 3 || value <= -3)  return '#FFFFFF'
  if (value >= 1.5 || value <= -1.5) return '#1A1D24'
  return '#6B7280'
}

function fmt(pct: number | null): string {
  if (pct === null) return '—'
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`
}

export default function MonthlyHeatmap({ isLoading = false, strategyId }: MonthlyHeatmapProps) {
  const chartRef      = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<echarts.ECharts | null>(null)
  const [show, setShow] = useState(false)

  const { data: monthlyData } = useQuery({
    queryKey: ['monthly-returns', strategyId],
    queryFn:  () => getMonthlyReturns(strategyId!),
    enabled:  !!strategyId,
  })

  // 预处理：把 rows → heatData + yAxisData，避免在 effect 里重复计算
  const { heatData, yAxisData, chartHeight } = useMemo(() => {
    const rows = monthlyData?.matrix ?? []
    const yAxisData: string[] = []
    const heatData: {
      value: [number, number, number | null, string]
      itemStyle: { color: string; borderWidth: number; borderColor: string; borderRadius: number }
      label:     { color: string; fontSize: number; fontWeight: number }
    }[] = []

    rows.forEach((row, yIdx) => {
      yAxisData.push(String(row.year))

      // 12 个月
      const monthValues: (number | null)[] = row.months ?? Array(12).fill(null)
      monthValues.forEach((val, xIdx) => {
        const pct = val !== null ? +(val * 100).toFixed(2) : null
        const cell: [number, number, number | null, string] = [xIdx, yIdx, pct, fmt(pct)]
        heatData.push({
          value: cell,
          itemStyle: { color: getColor(pct), borderWidth: 2, borderColor: '#fff', borderRadius: 4 },
          label:     { color: getTextColor(pct), fontSize: 11, fontWeight: 500 },
        })
      })

      // 年度列
      const yearly = row.yearly_return != null ? +(row.yearly_return * 100).toFixed(2) : null
      const yearCell: [number, number, number | null, string] = [12, yIdx, yearly, fmt(yearly)]
      heatData.push({
        value: yearCell,
        itemStyle: { color: getColor(yearly), borderWidth: 2, borderColor: '#fff', borderRadius: 4 },
        label:     { color: getTextColor(yearly), fontSize: 11, fontWeight: 700 },
      })
    })

    // 每行约 40px，最小 160px
    const chartHeight = Math.max(160, rows.length * 44)
    return { heatData, yAxisData, chartHeight }
  }, [monthlyData])

  useEffect(() => {
    if (isLoading) return
    const t = setTimeout(() => setShow(true), 700)
    return () => clearTimeout(t)
  }, [isLoading])

  // 初始化 / 销毁
  useEffect(() => {
    if (!chartRef.current || isLoading || !show) return
    const chart = echarts.init(chartRef.current)
    chartInstance.current = chart

    const handleResize = () => chart.resize()
    window.addEventListener('resize', handleResize)
    return () => {
      window.removeEventListener('resize', handleResize)
      chart.dispose()
      chartInstance.current = null
    }
  }, [isLoading, show])

  // 数据更新
  useEffect(() => {
    const chart = chartInstance.current
    if (!chart) return

    const option: EChartsCoreOption = {
      animation: true,
      animationDuration: 600,
      // visualMap 仍需声明，否则 heatmap 不渲染；但颜色由 itemStyle 覆盖
      visualMap: {
        show: false, min: -10, max: 10,
        inRange: { color: ['#DC2626', '#FFFFFF', '#16A34A'] },
      },
      tooltip: {
        formatter: (params: HeatmapParam) => {
          const d: HeatCell = params.data.value
          const monthLabel = X_AXIS_DATA[d[0]]
          const yearLabel  = yAxisData[d[1]]
          if (d[0] === 12) {
            return `
              <div style="font-size:12px;font-weight:600;color:#1A1D24">${yearLabel} 年度</div>
              <div style="font-size:16px;font-weight:700;margin-top:4px;color:#1A1D24">${d[3]}</div>`
          }
          return `
            <div style="font-size:11px;color:#9CA3AF">${yearLabel}年 ${monthLabel}</div>
            <div style="font-size:15px;font-weight:600;margin-top:4px;color:#1A1D24">${d[3]}</div>`
        },
        backgroundColor: '#fff',
        borderColor: 'transparent',
        borderRadius: 8,
        padding: [10, 14],
        extraCssText: 'box-shadow: 0 4px 12px rgba(0,0,0,0.08);',
      },
      grid: { top: 24, right: 8, bottom: 8, left: 8, containLabel: true },
      xAxis: {
        type: 'category',
        data: X_AXIS_DATA,
        position: 'top',
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: '#9CA3AF', fontSize: 11 },
        splitArea: { show: false },
      },
      yAxis: {
        type: 'category',
        data: yAxisData,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: '#1A1D24', fontSize: 12, fontWeight: 'bold' },
        splitArea: { show: false },
      },
      series: [{
        type: 'heatmap',
        data: heatData,
        label: {
          show: true,
          formatter: (p: HeatmapParam) => p.data.value[3],
        },
        itemStyle:  { borderWidth: 2, borderColor: '#fff', borderRadius: 4 },
        emphasis: {
          disabled: false,
          itemStyle: { borderWidth: 2, borderColor: '#1A1D24', shadowBlur: 8, shadowColor: 'rgba(0,0,0,0.15)' },
        },
      }],
    }

    chart.setOption(option, true)

    // 通知 echarts 容器高度已变化
    setTimeout(() => chart.resize(), 0)
  }, [heatData, yAxisData, show])

  // ── Skeleton ──
  if (isLoading || !show) {
    return (
      <div>
        <div className="flex items-center justify-between mb-4">
          <div className="h-5 skeleton w-20 rounded" />
          <div className="flex items-center gap-2">
            <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>+5%</span>
            <div className="flex gap-0.5">
              {LEGEND_COLORS.map(c => <div key={c} className="w-4 h-3 rounded skeleton" />)}
            </div>
            <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>-5%</span>
          </div>
        </div>
        <div className="w-full h-[200px] skeleton rounded-lg" />
      </div>
    )
  }

  // ── 空态 ──
  if (!monthlyData?.matrix?.length) {
    return (
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold" style={{ color: 'var(--gr-text)' }}>月度收益</h2>
        </div>
        <div
          className="flex items-center justify-center rounded-lg"
          style={{ height: 200, background: 'var(--gr-bg)', color: 'var(--gr-text-tertiary)', fontSize: 14 }}
        >
          暂无数据
        </div>
      </div>
    )
  }

  // ── 正常渲染 ──
  return (
    <div className="slide-up">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold" style={{ color: 'var(--gr-text)' }}>月度收益</h2>
        <div className="flex items-center gap-2">
          <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>+5%</span>
          <div className="flex gap-0.5">
            {LEGEND_COLORS.map((c) => (
              <div
                key={c}
                className="w-3 h-3 rounded-sm"
                style={{ background: c, border: c === '#FFFFFF' ? '1px solid #E5E7EB' : 'none' }}
              />
            ))}
          </div>
          <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>-5%</span>
        </div>
      </div>
      <div ref={chartRef} style={{ width: '100%', height: chartHeight }} />
    </div>
  )
}