import { useEffect, useRef } from "react";
import { LineChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  type GridComponentOption,
  type TooltipComponentOption,
} from "echarts/components";
import * as echarts from "echarts/core";
import type { EChartsCoreOption } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import type { LineSeriesOption } from "echarts/charts";
import type {
  EquityPoint,
  BenchmarkPoint,
  DrawdownPoint,
} from "../api/strategies";

echarts.use([GridComponent, TooltipComponent, LineChart, CanvasRenderer]);

type EquityChartOption = EChartsCoreOption & {
  grid?: GridComponentOption | GridComponentOption[];
  tooltip?: TooltipComponentOption;
  series?: LineSeriesOption[];
};

interface EquityCurveChartProps {
  equity: EquityPoint[];
  benchmark?: BenchmarkPoint[];
  drawdown?: DrawdownPoint[];
  height?: number;
}

export default function EquityCurveChart({
  equity,
  benchmark,
  drawdown,
  height = 400,
}: EquityCurveChartProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!chartRef.current || equity.length === 0) return;

    instanceRef.current?.dispose();

    const chart = echarts.init(chartRef.current);
    instanceRef.current = chart;

    const dates = equity.map((p) => p.date);
    const navData = equity.map((p) => p.nav);

    const series: LineSeriesOption[] = [
      {
        name: "NAV",
        type: "line",
        data: navData,
        smooth: true,
        lineStyle: { color: "#2563eb", width: 2 },
        itemStyle: { color: "#2563eb" },
        symbol: "none",
        yAxisIndex: 0,
      },
    ];

    if (benchmark && benchmark.length > 0) {
      const benchMap = new Map(benchmark.map((b) => [b.date, b.nav]));
      const benchAligned = dates.map((d) => benchMap.get(d) ?? null);
      series.push({
        name: "Benchmark",
        type: "line",
        data: benchAligned,
        smooth: true,
        lineStyle: { color: "#94a3b8", width: 1, type: "dashed" },
        itemStyle: { color: "#94a3b8" },
        symbol: "none",
        yAxisIndex: 0,
      });
    }

    const option: EquityChartOption = {
      tooltip: {
        trigger: "axis",
      },
      xAxis: [
        {
          type: "category",
          data: dates,
          axisLabel: { fontSize: 10, formatter: (v: string) => v.slice(0, 10) },
          gridIndex: 0,
        },
      ],
      yAxis: [
        {
          type: "value",
          name: "NAV",
          nameTextStyle: { fontSize: 11, color: "#64748b" },
          axisLabel: { fontSize: 10 },
          splitLine: { lineStyle: { color: "#f1f5f9" } },
        },
      ],
      grid: [{ left: 60, right: 20, top: 20, bottom: 40 }],
      series,
    };

    if (drawdown && drawdown.length > 0) {
      const ddMap = new Map(drawdown.map((d) => [d.date, d.drawdown]));
      const ddAligned = dates.map((d) => ddMap.get(d) ?? null);

      const existingXAxes = Array.isArray(option.xAxis)
        ? option.xAxis
        : option.xAxis
          ? [option.xAxis]
          : [];
      option.xAxis = [
        ...existingXAxes,
        {
          type: "category" as const,
          data: dates,
          show: false,
          gridIndex: 1,
        },
      ];

      const existingYAxes = Array.isArray(option.yAxis)
        ? option.yAxis
        : option.yAxis
          ? [option.yAxis]
          : [];
      option.yAxis = [
        ...existingYAxes,
        {
          type: "value" as const,
          name: "DD %",
          gridIndex: 1,
          nameTextStyle: { fontSize: 11, color: "#64748b" },
          axisLabel: {
            fontSize: 10,
            formatter: (v: number) => `${(v * 100).toFixed(0)}%`,
          },
          splitLine: { lineStyle: { color: "#f1f5f9" } },
        },
      ];

      const existingGrids = Array.isArray(option.grid)
        ? option.grid
        : option.grid
          ? [option.grid]
          : [];
      option.grid = [
        ...existingGrids,
        { left: 60, right: 20, top: "65%", bottom: 20 },
      ];

      series.push({
        name: "Drawdown",
        type: "line",
        data: ddAligned,
        smooth: true,
        lineStyle: { color: "#dc2626", width: 1 },
        areaStyle: { color: "rgba(220, 38, 38, 0.08)" },
        itemStyle: { color: "#dc2626" },
        symbol: "none",
        xAxisIndex: 1,
        yAxisIndex: 1,
      });
    }

    chart.setOption(option);

    const handleResize = () => chart.resize();
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.dispose();
    };
  }, [equity, benchmark, drawdown]);

  return (
    <div
      ref={chartRef}
      style={{ width: "100%", height, minHeight: height }}
    />
  );
}
