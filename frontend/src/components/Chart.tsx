import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, HeatmapChart, LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent, VisualMapComponent, LegendComponent, AxisPointerComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsCoreOption } from "echarts/core";
import { INK } from "../theme";

echarts.use([BarChart, LineChart, HeatmapChart, GridComponent, TooltipComponent, VisualMapComponent, LegendComponent, AxisPointerComponent, CanvasRenderer]);

// Habillage commun : axes et grille discrets, texte dans les encres neutres, info-bulles sombres.
export const baseOption = {
  backgroundColor: "transparent",
  textStyle: { color: INK.secondary, fontFamily: "Inter, system-ui, sans-serif", fontSize: 12 },
  grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
  tooltip: {
    backgroundColor: "#1d2024",
    borderColor: "#3a3e44",
    textStyle: { color: INK.primary, fontSize: 12 },
    extraCssText: "box-shadow: 0 8px 24px rgba(0,0,0,.5); border-radius: 8px;",
  },
};

export const axisStyle = {
  axisLine: { lineStyle: { color: INK.axis } },
  axisTick: { show: false },
  axisLabel: { color: INK.muted, fontSize: 11 },
  splitLine: { lineStyle: { color: INK.grid } },
};

export default function Chart({ option, className, ariaLabel }: { option: EChartsCoreOption; className?: string; ariaLabel?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const inst = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    inst.current = echarts.init(ref.current, undefined, { renderer: "canvas" });
    const ro = new ResizeObserver(() => inst.current?.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      inst.current?.dispose();
      inst.current = null;
    };
  }, []);

  useEffect(() => {
    inst.current?.setOption({ ...baseOption, ...option } as EChartsCoreOption, true);
  }, [option]);

  return <div ref={ref} className={`chart ${className ?? ""}`} role="img" aria-label={ariaLabel} />;
}
