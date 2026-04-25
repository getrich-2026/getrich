import { useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts/core'
import type { EChartsCoreOption } from 'echarts/core'
import { HeatmapChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([HeatmapChart, GridComponent, TooltipComponent, VisualMapComponent, CanvasRenderer])

interface MonthlyHeatmapProps {
  isLoading?: boolean
}

const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

const rawData = [
  { year: 2024, values: [3.2, -1.5, 4.1, 1.8, -0.8, 2.5, 1.2, -2.1, 3.5, 2.8, -0.5, 1.9], yearly: 16.8 },
  { year: 2025, values: [2.1, 1.5, -1.2, 3.8, 0.9, -0.3, 2.7, 1.4, 3.1, -1.1, 2.2, 1.6], yearly: 17.5 },
  { year: 2026, values: [2.8, 1.9, 2.5, null, null, null, null, null, null, null, null, null], yearly: 7.4 },
]

function getColor(value: number | null): string {
  if (value === null) return '#F5F6F8'
  if (value >= 5) return '#16A34A'
  if (value >= 3) return '#22C55E'
  if (value >= 1.5) return '#86EFAC'
  if (value >= 0.5) return '#BBF7D0'
  if (value >= -0.5) return '#FFFFFF'
  if (value >= -1.5) return '#FECACA'
  if (value >= -3) return '#F87171'
  return '#DC2626'
}

function getTextColor(value: number | null): string {
  if (value === null) return '#9CA3AF'
  if (value >= 3 || value <= -3) return '#FFFFFF'
  if (value >= 1.5 || value <= -1.5) return '#1A1D24'
  return '#6B7280'
}

export default function MonthlyHeatmap({ isLoading = false }: MonthlyHeatmapProps) {
  const chartRef = useRef<HTMLDivElement>(null)
  const [show, setShow] = useState(false)

  useEffect(() => {
    if (isLoading) return
    const t = setTimeout(() => setShow(true), 700)
    return () => clearTimeout(t)
  }, [isLoading])

  useEffect(() => {
    if (!chartRef.current || isLoading || !show) return
    const chart = echarts.init(chartRef.current)

    // Build heatmap data: [xIndex, yIndex, value, displayValue]
    const heatData: [number, number, number | null, string][] = []
    const yAxisData: string[] = []

    rawData.forEach((row, yIdx) => {
      yAxisData.push(String(row.year))
      row.values.forEach((val, xIdx) => {
        heatData.push([xIdx, yIdx, val, val !== null ? `${val >= 0 ? '+' : ''}${val.toFixed(1)}%` : '—'])
      })
      // Year total column
      heatData.push([12, yIdx, row.yearly, `${row.yearly >= 0 ? '+' : ''}${row.yearly.toFixed(1)}%`])
    })

    const xAxisData = [...months, 'Year']

    const option: EChartsCoreOption = {
      tooltip: {
        formatter: (params: any) => {
          const d = params.data
          const monthLabel = xAxisData[d[0]]
          const yearLabel = yAxisData[d[1]]
          if (d[0] === 12) {
            return `<div style="font-size:12px;font-weight:600">${yearLabel} 年度</div><div style="font-size:14px;margin-top:4px">${d[3]}</div>`
          }
          return `<div style="font-size:12px;color:#9CA3AF">${yearLabel}年 ${monthLabel}</div><div style="font-size:14px;font-weight:600;margin-top:4px">${d[3]}</div>`
        },
        backgroundColor: '#fff',
        borderColor: 'transparent',
        borderRadius: 8,
        padding: [10, 14],
        textStyle: { color: '#1A1D24' },
        extraCssText: 'box-shadow: 0 4px 12px rgba(0,0,0,0.08);',
      },
      grid: { top: 8, right: 8, bottom: 8, left: 8, containLabel: false },
      xAxis: {
        type: 'category',
        data: xAxisData,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: '#9CA3AF', fontSize: 11, fontFamily: '-apple-system, sans-serif' },
        splitArea: { show: false },
      },
      yAxis: {
        type: 'category',
        data: yAxisData,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: '#1A1D24', fontSize: 12, fontWeight: 600, fontFamily: '-apple-system, sans-serif' },
        splitArea: { show: false },
      },
      series: [{
        type: 'heatmap',
        data: heatData,
        label: {
          show: true,
          formatter: (p: any) => p.data[3],
          color: '#fff',
          fontSize: 11,
          fontFamily: '-apple-system, sans-serif',
        },
        itemStyle: {
          borderWidth: 2,
          borderColor: '#fff',
          borderRadius: 4,
        },
        emphasis: {
          itemStyle: {
            borderWidth: 2,
            borderColor: '#1A1D24',
            shadowBlur: 8,
            shadowColor: 'rgba(0,0,0,0.15)',
          },
        },
      }],
    }

    chart.setOption(option)

    // Custom item colors after render
    setTimeout(() => {
      const newData = heatData.map(d => ({
        value: d,
        itemStyle: {
          color: getColor(d[2]),
          borderWidth: 2,
          borderColor: '#fff',
          borderRadius: 4,
        },
        label: {
          color: getTextColor(d[2]),
          fontSize: 11,
          fontFamily: '-apple-system, sans-serif',
          fontWeight: d[0] === 12 ? 700 : 500,
        },
      }))
      chart.setOption({ series: [{ data: newData }] })
    }, 50)

    const handleResize = () => chart.resize()
    window.addEventListener('resize', handleResize)
    return () => { window.removeEventListener('resize', handleResize); chart.dispose() }
  }, [isLoading, show])

  if (isLoading || !show) {
    return (
      <div>
        <div className="flex items-center justify-between mb-4">
          <div className="h-5 skeleton w-20" />
          <div className="flex items-center gap-2">
            <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>+5%</span>
            <div className="w-4 h-3 rounded skeleton" />
            <div className="w-4 h-3 rounded skeleton" />
            <div className="w-4 h-3 rounded skeleton" />
            <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>-5%</span>
          </div>
        </div>
        <div className="w-full h-[200px] skeleton rounded-lg" />
      </div>
    )
  }

  return (
    <div className="slide-up">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold" style={{ color: 'var(--gr-text)' }}>月度收益</h2>
        <div className="flex items-center gap-2">
          <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>+5%</span>
          <div className="flex gap-0.5">
            <div className="w-3 h-3 rounded-sm" style={{ background: '#DC2626' }} />
            <div className="w-3 h-3 rounded-sm" style={{ background: '#F87171' }} />
            <div className="w-3 h-3 rounded-sm" style={{ background: '#FECACA' }} />
            <div className="w-3 h-3 rounded-sm" style={{ background: '#FFFFFF', border: '1px solid #E5E7EB' }} />
            <div className="w-3 h-3 rounded-sm" style={{ background: '#BBF7D0' }} />
            <div className="w-3 h-3 rounded-sm" style={{ background: '#86EFAC' }} />
            <div className="w-3 h-3 rounded-sm" style={{ background: '#22C55E' }} />
            <div className="w-3 h-3 rounded-sm" style={{ background: '#16A34A' }} />
          </div>
          <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>-5%</span>
        </div>
      </div>
      <div ref={chartRef} style={{ width: '100%', height: 220 }} />
    </div>
  )
}
