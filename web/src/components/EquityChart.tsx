import { useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, CanvasRenderer])

interface EquityChartProps {
  isLoading?: boolean
}

const timeRanges = ['1M', '3M', '6M', '1Y', '3Y', 'ALL']

function generateEquityData(days: number) {
  const dates: string[] = []
  const nav: number[] = []
  const benchmark: number[] = []
  const drawdown: number[] = []
  let currentNav = 1.0
  let currentBenchmark = 1.0
  let peak = 1.0
  const startDate = new Date('2020-01-02')

  for (let i = 0; i < days; i++) {
    const date = new Date(startDate)
    date.setDate(date.getDate() + i)
    dates.push(date.toISOString().split('T')[0])
    const dailyReturn = (Math.random() - 0.45) * 0.008
    const benchReturn = (Math.random() - 0.48) * 0.01
    currentNav *= 1 + dailyReturn
    currentBenchmark *= 1 + benchReturn
    if (currentNav > peak) peak = currentNav
    const dd = (currentNav - peak) / peak
    nav.push(Number(currentNav.toFixed(4)))
    benchmark.push(Number(currentBenchmark.toFixed(4)))
    drawdown.push(Number(dd.toFixed(4)))
  }
  return { dates, nav, benchmark, drawdown }
}

export default function EquityChart({ isLoading = false }: EquityChartProps) {
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<any>(null)
  const [activeRange, setActiveRange] = useState('ALL')
  const [show, setShow] = useState(false)
  const data = useRef(generateEquityData(1540))

  useEffect(() => {
    if (isLoading) return
    const t = setTimeout(() => setShow(true), 400)
    return () => clearTimeout(t)
  }, [isLoading])

  useEffect(() => {
    if (!chartRef.current || isLoading || !show) return
    const chart = echarts.init(chartRef.current)
    chartInstance.current = chart
    const { dates, nav, benchmark, drawdown } = data.current

    chart.setOption({
      animation: true, animationDuration: 800,
      grid: [
        { left: 60, right: 60, top: 40, height: '55%' },
        { left: 60, right: 60, top: '72%', height: '18%' },
      ],
      xAxis: [
        { type: 'category', data: dates, gridIndex: 0, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: '#9CA3AF', fontSize: 11, interval: Math.floor(dates.length / 8) } },
        { type: 'category', data: dates, gridIndex: 1, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { show: false } },
      ],
      yAxis: [
        { type: 'value', gridIndex: 0, axisLine: { show: false }, axisTick: { show: false }, splitLine: { lineStyle: { color: '#F0F0F0' } }, axisLabel: { color: '#9CA3AF', fontSize: 11, formatter: (v: any) => Number(v).toFixed(2) } },
        { type: 'value', gridIndex: 1, axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false }, axisLabel: { color: '#9CA3AF', fontSize: 11, formatter: (v: any) => `${(Number(v) * 100).toFixed(0)}%` } },
      ],
      dataZoom: [{ type: 'slider', xAxisIndex: [0, 1], bottom: 0, height: 24, borderColor: 'transparent', backgroundColor: '#F5F6F8', fillerColor: 'rgba(232, 71, 63, 0.15)', handleStyle: { color: '#E8473F', borderColor: '#E8473F' }, textStyle: { color: '#9CA3AF', fontSize: 11 }, brushSelect: false }],
      tooltip: { trigger: 'axis', backgroundColor: '#fff', borderColor: 'transparent', borderRadius: 8, padding: [12, 16], textStyle: { color: '#1A1D24', fontSize: 12 }, extraCssText: 'box-shadow: 0 4px 12px rgba(0,0,0,0.08);' },
      legend: { data: ['策略净值', '中证500'], right: 0, top: 0, textStyle: { color: '#6B7280', fontSize: 12 }, itemWidth: 16, itemHeight: 2 },
      series: [
        { name: '策略净值', type: 'line', data: nav, smooth: true, symbol: 'none', lineStyle: { color: '#E8473F', width: 2 }, xAxisIndex: 0, yAxisIndex: 0 },
        { name: '中证500', type: 'line', data: benchmark, smooth: true, symbol: 'none', lineStyle: { color: '#3B82F6', width: 1.5, type: [4, 2] as any }, xAxisIndex: 0, yAxisIndex: 0 },
        { name: '回撤', type: 'line', data: drawdown, smooth: true, symbol: 'none', lineStyle: { color: '#E8473F', width: 0 }, areaStyle: { color: 'rgba(232, 71, 63, 0.15)' }, xAxisIndex: 1, yAxisIndex: 1 },
      ],
    })

    const handleResize = () => chart.resize()
    window.addEventListener('resize', handleResize)
    return () => { window.removeEventListener('resize', handleResize); chart.dispose() }
  }, [isLoading, show])

  if (isLoading || !show) {
    return (
      <div className="w-full">
        <div className="flex gap-1 mb-4">
          {timeRanges.map((_, i) => <div key={i} className="w-12 h-8 skeleton rounded-md" />)}
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
            style={{ background: activeRange === range ? 'var(--gr-text)' : 'var(--gr-bg)', color: activeRange === range ? '#fff' : 'var(--gr-text-secondary)' }}
          >
            {range}
          </button>
        ))}
      </div>
      <div ref={chartRef} style={{ width: '100%', height: 360 }} />
    </div>
  )
}
