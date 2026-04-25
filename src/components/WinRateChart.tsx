import { useEffect, useRef } from 'react'
import * as echarts from 'echarts/core'
import { PieChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([PieChart, CanvasRenderer])

interface WinRateChartProps {
  winRate: number
}

export default function WinRateChart({ winRate }: WinRateChartProps) {
  const chartRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!chartRef.current) return
    const chart = echarts.init(chartRef.current)
    chart.setOption({
      series: [{
        type: 'pie',
        radius: ['65%', '85%'],
        avoidLabelOverlap: false,
        label: { show: false },
        emphasis: { scale: false },
        data: [
          { value: winRate * 100, name: '胜利', itemStyle: { color: '#22C55E' } },
          { value: (1 - winRate) * 100, name: '失败', itemStyle: { color: '#E8473F' } },
        ],
      }],
    })
    const handleResize = () => chart.resize()
    window.addEventListener('resize', handleResize)
    return () => { window.removeEventListener('resize', handleResize); chart.dispose() }
  }, [winRate])

  return (
    <div className="relative" style={{ width: 120, height: 120 }}>
      <div ref={chartRef} style={{ width: '100%', height: '100%' }} />
      <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
        <span className="text-lg font-bold tabular" style={{ color: 'var(--gr-text)' }}>{(winRate * 100).toFixed(1)}%</span>
        <span className="text-xs" style={{ color: 'var(--gr-text-tertiary)' }}>胜率</span>
      </div>
    </div>
  )
}
