import { useEffect, useRef, useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { api } from '@/lib/api'

echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, CanvasRenderer])

interface EquityChartProps {
  isLoading?: boolean
  strategyId?: string
}

// ECharts 的 tooltip formatter 入参是个很宽的联合类型，直接用会逼出一堆断言。
// 这里只声明本图实际读到的字段，够用且不失真。
interface AxisTooltipParam {
  axisValue: string
  seriesName: string
  marker: string
  value: number
}

const timeRanges = ['1M', '3M', '6M', '1Y', '3Y', 'ALL']

function getRangeStartDate(range: string): Date | null {
  const now = new Date()
  switch (range) {
    case '1M': return new Date(now.getFullYear(), now.getMonth() - 1, now.getDate())
    case '3M': return new Date(now.getFullYear(), now.getMonth() - 3, now.getDate())
    case '6M': return new Date(now.getFullYear(), now.getMonth() - 6, now.getDate())
    case '1Y': return new Date(now.getFullYear() - 1, now.getMonth(), now.getDate())
    case '3Y': return new Date(now.getFullYear() - 3, now.getMonth(), now.getDate())
    default:   return null
  }
}

export default function EquityChart({ isLoading = false, strategyId }: EquityChartProps) {
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<echarts.ECharts | null>(null)
  const [activeRange, setActiveRange] = useState('ALL')
  const [show, setShow] = useState(false)

  const { data: equityData } = useQuery({
    queryKey: ['equity-curve', strategyId],
    queryFn: () => api.getEquityCurve(strategyId!),
    enabled: !!strategyId,
  })

  // 根据时间范围过滤数据
  const filteredData = useMemo(() => {
    const dates: string[]    = equityData?.dates    ?? []
    const nav: number[]      = equityData?.nav      ?? []
    const benchmark: number[]= equityData?.benchmark ?? []
    const drawdown: number[] = equityData?.drawdown  ?? []

    const startDate = getRangeStartDate(activeRange)
    if (!startDate || dates.length === 0) {
      return { dates, nav, benchmark, drawdown }
    }

    const startStr = startDate.toISOString().split('T')[0]
    const startIdx = dates.findIndex(d => d >= startStr)
    if (startIdx === -1) return { dates, nav, benchmark, drawdown }

    return {
      dates:     dates.slice(startIdx),
      nav:       nav.slice(startIdx),
      benchmark: benchmark.slice(startIdx),
      drawdown:  drawdown.slice(startIdx),
    }
  }, [equityData, activeRange])

  useEffect(() => {
    if (isLoading) return
    const t = setTimeout(() => setShow(true), 400)
    return () => clearTimeout(t)
  }, [isLoading])

  // 初始化图表
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

  // 数据变化时更新图表
  useEffect(() => {
    const chart = chartInstance.current
    if (!chart) return

    const { dates, nav, benchmark, drawdown } = filteredData

    chart.setOption({
      animation: true,
      animationDuration: 600,
      grid: [
        { left: 60, right: 20, top: 40, height: '55%' },
        { left: 60, right: 20, top: '72%', height: '18%' },
      ],
      xAxis: [
        {
          type: 'category', data: dates, gridIndex: 0,
          axisLine: { show: false }, axisTick: { show: false },
          axisLabel: {
            color: '#9CA3AF', fontSize: 11,
            interval: Math.max(0, Math.floor(dates.length / 6) - 1),
          },
        },
        {
          type: 'category', data: dates, gridIndex: 1,
          axisLine: { show: false }, axisTick: { show: false },
          axisLabel: { show: false },
        },
      ],
      yAxis: [
        {
          type: 'value', gridIndex: 0,
          axisLine: { show: false }, axisTick: { show: false },
          splitLine: { lineStyle: { color: '#F0F0F0' } },
          axisLabel: {
            color: '#9CA3AF', fontSize: 11,
            formatter: (v: number) => v.toFixed(2),
          },
        },
        {
          type: 'value', gridIndex: 1,
          axisLine: { show: false }, axisTick: { show: false },
          splitLine: { show: false },
          axisLabel: {
            color: '#9CA3AF', fontSize: 11,
            formatter: (v: number) => `${(v * 100).toFixed(0)}%`,
          },
        },
      ],
      dataZoom: [{
        type: 'inside', xAxisIndex: [0, 1],
      }],
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#fff',
        borderColor: 'transparent',
        borderRadius: 8,
        padding: [12, 16],
        textStyle: { color: '#1A1D24', fontSize: 12 },
        extraCssText: 'box-shadow: 0 4px 12px rgba(0,0,0,0.08);',
        formatter: (params: AxisTooltipParam[]) => {
          const date = params[0]?.axisValue ?? ''
          const lines = params
            .filter((p) => p.seriesName !== '回撤')
            .map((p) =>
              `<div style="display:flex;justify-content:space-between;gap:24px;margin-top:4px">
                <span style="color:#9CA3AF">${p.marker}${p.seriesName}</span>
                <span style="font-weight:600">${Number(p.value).toFixed(4)}</span>
              </div>`
            ).join('')
          return `<div style="font-size:11px;color:#9CA3AF;margin-bottom:2px">${date}</div>${lines}`
        },
      },
      legend: {
        data: benchmark.length > 0 ? ['策略净值', '基准'] : ['策略净值'],
        right: 0, top: 0,
        textStyle: { color: '#6B7280', fontSize: 12 },
        itemWidth: 16, itemHeight: 2,
      },
      series: [
        {
          name: '策略净值', type: 'line', data: nav,
          smooth: false, symbol: 'none',
          lineStyle: { color: '#E8473F', width: 2 },
          xAxisIndex: 0, yAxisIndex: 0,
        },
        {
          name: '基准', type: 'line', data: benchmark,
          smooth: false, symbol: 'none',
          lineStyle: { color: '#3B82F6', width: 1.5, type: [4, 2] },
          xAxisIndex: 0, yAxisIndex: 0,
        },
        {
          name: '回撤', type: 'line', data: drawdown,
          smooth: false, symbol: 'none',
          lineStyle: { color: '#E8473F', width: 0 },
          areaStyle: { color: 'rgba(232, 71, 63, 0.15)' },
          xAxisIndex: 1, yAxisIndex: 1,
        },
      ],
    }, true) // true = 完整替换，避免动画叠加
  }, [filteredData, show])

  if (isLoading || !show) {
    return (
      <div className="w-full">
        <div className="flex gap-1 mb-4">
          {timeRanges.map((_, i) => (
            <div key={i} className="w-12 h-8 skeleton rounded-md" />
          ))}
        </div>
        <div className="w-full h-[360px] skeleton rounded-lg" />
      </div>
    )
  }

  return (
    <div className="slide-up">
      <div className="flex gap-1 mb-4">
        {timeRanges.map((range) => (
          <button
            key={range}
            onClick={() => setActiveRange(range)}
            className="px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-150"
            style={{
              background: activeRange === range ? 'var(--gr-text)' : 'var(--gr-bg)',
              color: activeRange === range ? '#fff' : 'var(--gr-text-secondary)',
            }}
          >
            {range}
          </button>
        ))}
      </div>
      <div ref={chartRef} style={{ width: '100%', height: 360 }} />
    </div>
  )
}