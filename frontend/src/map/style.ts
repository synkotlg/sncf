import type { ExpressionSpecification, StyleSpecification } from "maplibre-gl";
import type { Settings } from "../types";
import { INFRA_COLORS, SEQUENTIAL, SLOT_COLORS, TRAIN_TYPE_COLORS } from "../theme";

const EMPTY = { type: "FeatureCollection", features: [] } as const;

function expandTiles(url: string): string[] {
  if (url.includes("{s}")) return ["a", "b", "c", "d"].map((s) => url.replace("{s}", s));
  return [url];
}

export function buildStyle(origin: string, settings: Settings | null): StyleSpecification {
  const online = settings?.online_basemap ?? true;
  const sources: StyleSpecification["sources"] = {
    countries: { type: "geojson", data: `${origin}/api/reference/basemap` },
    "rail-lines": { type: "vector", tiles: [`${origin}/api/tiles/lines/{z}/{x}/{y}.pbf`], minzoom: 0, maxzoom: 14 },
    "rail-routes": { type: "vector", tiles: [`${origin}/api/tiles/routes/{z}/{x}/{y}.pbf`], minzoom: 0, maxzoom: 14 },
    "rail-stations": { type: "vector", tiles: [`${origin}/api/tiles/stations/{z}/{x}/{y}.pbf`], minzoom: 0, maxzoom: 14 },
    "fines-seg": { type: "geojson", data: EMPTY as any },
    "fines-od": { type: "geojson", data: EMPTY as any },
    "fines-st": { type: "geojson", data: EMPTY as any },
    "fines-pt": { type: "geojson", data: EMPTY as any },
    path: { type: "geojson", data: EMPTY as any },
    highlight: { type: "geojson", data: EMPTY as any },
  };
  if (online && settings?.basemap_url) {
    sources["basemap"] = {
      type: "raster",
      tiles: expandTiles(settings.basemap_url),
      tileSize: 256,
      attribution: settings.basemap_attribution,
      maxzoom: 19,
    };
  }
  if (settings?.openrailwaymap_overlay) {
    sources["orm"] = {
      type: "raster",
      tiles: ["a", "b", "c"].map((s) => `https://${s}.tiles.openrailwaymap.org/standard/{z}/{x}/{y}.png`),
      tileSize: 256,
      attribution: "Style : OpenRailwayMap (CC-BY-SA 2.0), données (c) OpenStreetMap",
      maxzoom: 19,
    };
  }
  const infraColor: ExpressionSpecification = [
    "match", ["get", "infra_type"],
    "lgv", INFRA_COLORS.lgv,
    "classique", INFRA_COLORS.classique,
    "raccordement", INFRA_COLORS.raccordement,
    INFRA_COLORS.inconnu,
  ];
  const routeColor: ExpressionSpecification = [
    "match", ["get", "category"],
    ...Object.entries(TRAIN_TYPE_COLORS).flat(),
    TRAIN_TYPE_COLORS.AUTRE,
  ] as unknown as ExpressionSpecification;
  const layers: StyleSpecification["layers"] = [
    { id: "background", type: "background", paint: { "background-color": "#0b0c0e" } },
    {
      id: "countries-fill", type: "fill", source: "countries",
      paint: { "fill-color": ["case", ["get", "focus"], "#14161a", "#0f1012"], "fill-opacity": online ? 0.0 : 1 },
    },
  ];
  if (sources["basemap"]) layers.push({ id: "basemap", type: "raster", source: "basemap", paint: { "raster-opacity": 0.92, "raster-saturation": -0.4 } });
  layers.push({
    id: "countries-line", type: "line", source: "countries",
    paint: { "line-color": ["case", ["get", "focus"], "#4a4f56", "#2c2f34"], "line-width": ["interpolate", ["linear"], ["zoom"], 4, 0.6, 9, 1.4] },
  });
  if (sources["orm"]) layers.push({ id: "orm", type: "raster", source: "orm", paint: { "raster-opacity": 0.75 } });
  layers.push(
    {
      id: "rail-branch", type: "line", source: "rail-lines", "source-layer": "lines",
      filter: ["==", ["get", "infra_type"], "raccordement"],
      paint: { "line-color": infraColor, "line-width": ["interpolate", ["linear"], ["zoom"], 5, 0.5, 10, 1.4, 14, 2.2], "line-dasharray": [2, 1.5] },
    },
    {
      id: "rail-lines", type: "line", source: "rail-lines", "source-layer": "lines",
      filter: ["!=", ["get", "infra_type"], "raccordement"],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": infraColor,
        "line-width": ["interpolate", ["linear"], ["zoom"], 4, ["case", ["==", ["get", "infra_type"], "lgv"], 1.4, 0.8], 10, ["case", ["==", ["get", "infra_type"], "lgv"], 3, 1.8], 14, 3.6],
        "line-opacity": 0.85,
      },
    },
    {
      id: "rail-routes", type: "line", source: "rail-routes", "source-layer": "routes",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": routeColor, "line-width": ["interpolate", ["linear"], ["zoom"], 4, 1.2, 10, 3, 14, 5], "line-opacity": 0.85 },
    },
    {
      id: "highlight", type: "line", source: "highlight",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": "#ffffff", "line-width": ["interpolate", ["linear"], ["zoom"], 4, 5, 12, 10], "line-opacity": 0.28 },
    },
    {
      id: "fines-od", type: "line", source: "fines-od",
      paint: { "line-color": "#c3c2b7", "line-width": 1.6, "line-dasharray": [1.5, 2], "line-opacity": 0.8 },
    },
    {
      id: "fines-seg-casing", type: "line", source: "fines-seg",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": "#0b0c0e", "line-width": 6, "line-opacity": 0.9 },
    },
    {
      id: "fines-seg", type: "line", source: "fines-seg",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": SEQUENTIAL[2], "line-width": 4 },
    },
    {
      id: "fines-st", type: "circle", source: "fines-st",
      paint: {
        "circle-color": SEQUENTIAL[3],
        "circle-opacity": 0.85,
        "circle-radius": 6,
        "circle-stroke-color": "#0b0c0e",
        "circle-stroke-width": 2,
      },
    },
    {
      id: "path-casing", type: "line", source: "path",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": "#0b0c0e", "line-width": ["interpolate", ["linear"], ["zoom"], 4, 6, 12, 10] },
    },
    {
      id: "path", type: "line", source: "path",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": "#f0efec", "line-width": ["interpolate", ["linear"], ["zoom"], 4, 3, 12, 6] },
    },
    {
      id: "rail-stations", type: "circle", source: "rail-stations", "source-layer": "stations",
      paint: {
        "circle-color": ["case", ["==", ["get", "kind"], "station"], "#d9d7d2", "#6b7078"],
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, ["match", ["get", "importance"], 1, 3, 2, 2.2, 1.5], 10, ["match", ["get", "importance"], 1, 5.5, 2, 4.5, 3.5], 14, 6],
        "circle-stroke-color": "#0b0c0e",
        "circle-stroke-width": 1.2,
      },
    },
    {
      id: "fines-pt", type: "circle", source: "fines-pt", minzoom: 7,
      paint: {
        "circle-color": ["case", ["get", "is_demo"], "#9085e9", "#f0efec"],
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 3, 12, 6],
        "circle-stroke-color": "#0b0c0e",
        "circle-stroke-width": 1.5,
      },
    },
    {
      id: "station-labels", type: "symbol", source: "rail-stations", "source-layer": "stations",
      filter: ["any", ["<=", ["get", "importance"], 1], ["all", ["<=", ["get", "importance"], 2], [">=", ["zoom"], 6.5]], [">=", ["zoom"], 9]],
      layout: {
        "text-field": ["get", "name"],
        "text-font": ["NotoSans-Regular"],
        "text-size": ["interpolate", ["linear"], ["zoom"], 5, ["match", ["get", "importance"], 1, 12, 10.5], 12, ["match", ["get", "importance"], 1, 14, 2, 13, 12]],
        "text-offset": [0, 0.9],
        "text-anchor": "top",
        "text-max-width": 9,
        "text-optional": true,
        "symbol-sort-key": ["get", "importance"],
      },
      paint: { "text-color": "#dedcd6", "text-halo-color": "#0b0c0e", "text-halo-width": 1.6 },
    },
  );
  return {
    version: 8,
    glyphs: `${origin}/fonts/{fontstack}/{range}.pbf`,
    sources,
    layers,
  };
}

export function metricColor(metric: string, max: number): ExpressionSpecification | string {
  if (metric === "slot") {
    return ["match", ["coalesce", ["get", "dominant_slot"], ""], ...Object.entries(SLOT_COLORS).flat(), "#8b9097"] as unknown as ExpressionSpecification;
  }
  const key = metric === "time" ? "count" : metric;
  const m = Math.max(max, 1e-6);
  const stops = SEQUENTIAL.flatMap((c, i) => [(m * i) / (SEQUENTIAL.length - 1), c]);
  return ["interpolate", ["linear"], ["coalesce", ["get", key], 0], ...stops] as unknown as ExpressionSpecification;
}

export function metricWidth(metric: string, max: number): ExpressionSpecification | number {
  if (metric === "slot") return ["interpolate", ["linear"], ["get", "count"], 1, 3, Math.max(2, max), 8] as unknown as ExpressionSpecification;
  const key = metric === "time" ? "count" : metric;
  const m = Math.max(max, 1e-6);
  return ["interpolate", ["linear"], ["coalesce", ["get", key], 0], 0, 2.5, m, 9] as unknown as ExpressionSpecification;
}
