import type { EChartsCoreOption } from "echarts/core";
import { money, monthLabel, number } from "../format";
import { INK, SEQUENTIAL, SERIES } from "../theme";
import { axisStyle } from "./Chart";

export type Metric = "count" | "total" | "mean";

export const METRIC_LABEL: Record<Metric, string> = {
  count: "Nombre d'amendes",
  total: "Montant total",
  mean: "Montant moyen",
};

export function fmtMetric(m: Metric, v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return m === "count" ? number(v) : money(v);
}

interface Row {
  count: number;
  total: number;
  mean: number | null;
  median?: number | null;
}

function tooltipFor(title: string, r: Row, m: Metric): string {
  const lines = [
    `<b>${title}</b>`,
    `${m === "count" ? "<b>" : ""}Nombre : ${number(r.count)}${m === "count" ? "</b>" : ""}`,
    `${m === "total" ? "<b>" : ""}Montant total : ${money(r.total)}${m === "total" ? "</b>" : ""}`,
    `${m === "mean" ? "<b>" : ""}Montant moyen : ${money(r.mean)}${m === "mean" ? "</b>" : ""}`,
  ];
  if (r.median !== undefined) lines.push(`Montant médian : ${money(r.median)}`);
  return lines.join("<br/>");
}

// Barres verticales sur une échelle catégorielle ordonnée (heures, jours, mois).
export function columnChart(labels: string[], rows: Row[], metric: Metric, color = SERIES[0], titles?: string[]): EChartsCoreOption {
  return {
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow", shadowStyle: { color: "rgba(255,255,255,0.04)" } },
      formatter: (params: any) => {
        const p = Array.isArray(params) ? params[0] : params;
        return tooltipFor(titles?.[p.dataIndex] ?? labels[p.dataIndex], rows[p.dataIndex], metric);
      },
    },
    xAxis: { type: "category", data: labels, ...axisStyle, splitLine: { show: false } },
    yAxis: {
      type: "value",
      ...axisStyle,
      minInterval: metric === "count" ? 1 : undefined,
      axisLabel: { ...axisStyle.axisLabel, formatter: (v: number) => (metric === "count" ? String(v) : `${v} €`) },
    },
    series: [
      {
        type: "bar",
        data: rows.map((r) => (metric === "mean" ? r.mean ?? 0 : r[metric])),
        itemStyle: { color, borderRadius: [4, 4, 0, 0] },
        barMaxWidth: 22,
        barCategoryGap: "18%",
        emphasis: { itemStyle: { color: "#5598e7" } },
      },
    ],
  };
}

// Évolution mensuelle (une seule mesure, un seul axe).
export function monthsChart(months: { month: string; count: number; total: number; mean: number | null }[], metric: Metric): EChartsCoreOption {
  const labels = months.map((m) => monthLabel(m.month));
  return {
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "line", lineStyle: { color: INK.muted, type: "dashed" } },
      formatter: (params: any) => {
        const p = Array.isArray(params) ? params[0] : params;
        return tooltipFor(labels[p.dataIndex], months[p.dataIndex], metric);
      },
    },
    xAxis: { type: "category", data: labels, boundaryGap: true, ...axisStyle, splitLine: { show: false }, axisLabel: { ...axisStyle.axisLabel, hideOverlap: true } },
    yAxis: {
      type: "value",
      ...axisStyle,
      minInterval: metric === "count" ? 1 : undefined,
      axisLabel: { ...axisStyle.axisLabel, formatter: (v: number) => (metric === "count" ? String(v) : `${v} €`) },
    },
    series: [
      {
        type: "line",
        data: months.map((m) => (metric === "mean" ? m.mean ?? 0 : m[metric])),
        smooth: false,
        symbol: "circle",
        symbolSize: 7,
        lineStyle: { width: 2, color: SERIES[0] },
        itemStyle: { color: SERIES[0], borderColor: INK.surface, borderWidth: 2 },
        areaStyle: { color: "rgba(57,135,229,0.12)" },
      },
    ],
  };
}

// Carte de chaleur jour x heure (séquentiel, une teinte).
export function heatmapChart(cells: { weekday: number; hour: number; count: number; total: number }[], weekdays: string[]): EChartsCoreOption {
  const max = Math.max(1, ...cells.map((c) => c.count));
  const hours = Array.from({ length: 24 }, (_, h) => `${h}h`);
  return {
    tooltip: {
      position: "top",
      formatter: (p: any) => {
        const [h, d, c] = p.data;
        const cell = cells.find((x) => x.hour === h && x.weekday === d);
        return `<b>${weekdays[d]} ${h}h-${h + 1}h</b><br/>Nombre : ${c}<br/>Montant total : ${money(cell?.total ?? 0)}`;
      },
    },
    grid: { left: 8, right: 16, top: 8, bottom: 48, containLabel: true },
    xAxis: { type: "category", data: hours, ...axisStyle, splitLine: { show: false }, axisLabel: { ...axisStyle.axisLabel, interval: 1 } },
    yAxis: { type: "category", data: weekdays, ...axisStyle, splitLine: { show: false }, inverse: true },
    visualMap: {
      min: 0,
      max,
      calculable: false,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      itemWidth: 12,
      itemHeight: 140,
      text: [`${max} amende(s)`, "0"],
      textStyle: { color: INK.muted },
      inRange: { color: ["#1d2024", ...SEQUENTIAL.slice(1)] },
    },
    series: [
      {
        type: "heatmap",
        data: cells.map((c) => [c.hour, c.weekday, c.count]),
        itemStyle: { borderColor: INK.surface, borderWidth: 2, borderRadius: 3 },
        emphasis: { itemStyle: { borderColor: INK.primary, borderWidth: 1 } },
      },
    ],
  };
}
