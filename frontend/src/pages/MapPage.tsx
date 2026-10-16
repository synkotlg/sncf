import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource, type MapGeoJSONFeature, type Map as MLMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Link, useSearchParams } from "react-router-dom";
import { api, qs } from "../api";
import { label, useApp } from "../components/AppContext";
import Chart from "../components/Chart";
import { columnChart } from "../components/charts";
import FiltersBar, { filterQuery } from "../components/FiltersBar";
import StationPicker from "../components/StationPicker";
import { date, money, monthLabel, number } from "../format";
import { buildStyle, metricColor, metricWidth } from "../map/style";
import { GEO_COLORS, INFRA_COLORS, SEQUENTIAL, SLOT_COLORS, TRAIN_TYPE_COLORS, TRAIN_TYPE_ORDER } from "../theme";
import type { FilterState, Fine, MapLayers, ReferenceStatus, StationCandidate, Stats } from "../types";

type Tab = "layers" | "fines" | "details" | "route";
type Mode = "count" | "total" | "mean" | "slot" | "time";

const MODES: { id: Mode; label: string }[] = [
  { id: "count", label: "Nombre" },
  { id: "total", label: "Montant total" },
  { id: "mean", label: "Montant moyen" },
  { id: "slot", label: "Horaire" },
  { id: "time", label: "Évolution" },
];

interface Selection {
  kind: "station" | "line" | "route" | "segment" | "fine" | "od";
  title: string;
  data: any;
  stats?: Stats | null;
}

const INTERACTIVE = ["fines-pt", "fines-st", "fines-seg", "fines-od", "rail-stations", "rail-routes", "rail-lines", "rail-branch"];

function monthBounds(ym: string): [string, string] {
  const [y, m] = ym.split("-").map(Number);
  const last = new Date(y, m, 0).getDate();
  return [`${ym}-01`, `${ym}-${String(last).padStart(2, "0")}`];
}

export default function MapPage() {
  const { settings, options, dataVersion } = useApp();
  const [params] = useSearchParams();
  const container = useRef<HTMLDivElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const [ready, setReady] = useState(false);
  const [tab, setTab] = useState<Tab>("fines");
  const [ref, setRef] = useState<ReferenceStatus | null>(null);
  const [vis, setVis] = useState({ lines: true, stations: true, routes: true, fines: true, points: true, od: true, basemap: true, orm: true });
  const [infra, setInfra] = useState<Record<string, boolean>>({ lgv: true, classique: true, raccordement: true, inconnu: true });
  const [cats, setCats] = useState<Record<string, boolean>>(Object.fromEntries(TRAIN_TYPE_ORDER.map((c) => [c, true])));
  const [mode, setMode] = useState<Mode>("count");
  const [filters, setFilters] = useState<FilterState>({});
  const [layers, setLayers] = useState<MapLayers | null>(null);
  const [months, setMonths] = useState<string[]>([]);
  const [monthIdx, setMonthIdx] = useState(0);
  const [cumulative, setCumulative] = useState(true);
  const [playing, setPlaying] = useState(false);
  const [fines, setFines] = useState<Record<number, Fine>>({});
  const [sel, setSel] = useState<Selection | null>(null);
  const [from, setFrom] = useState<StationCandidate | null>(null);
  const [to, setTo] = useState<StationCandidate | null>(null);
  const [via, setVia] = useState<StationCandidate | null>(null);
  const [pathRes, setPathRes] = useState<any>(null);
  const [pathErr, setPathErr] = useState<string | null>(null);
  const [basemapError, setBasemapError] = useState(false);

  // ------------------------------------------------------------------ init carte
  useEffect(() => {
    if (!container.current || !settings) return;
    const map = new maplibregl.Map({
      container: container.current,
      style: buildStyle(window.location.origin, settings),
      center: [3.4, 47.6],
      zoom: 5.1,
      minZoom: 3,
      maxZoom: 17,
      attributionControl: { compact: true, customAttribution: "Réseau : SNCF Réseau, Infrabel, OSM, Natural Earth selon import" },
      dragRotate: false,
    });
    map.touchZoomRotate.disableRotation();
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.FullscreenControl({ container: wrap.current ?? undefined }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");
    let warned = false;
    map.on("error", (e: any) => {
      if (!warned && e?.sourceId === "basemap") {
        warned = true;
        setBasemapError(true);
        if (map.getLayer("basemap")) map.setLayoutProperty("basemap", "visibility", "none");
        if (map.getLayer("countries-fill")) map.setPaintProperty("countries-fill", "fill-opacity", 1);
      }
    });
    map.on("load", () => setReady(true));
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
      setReady(false);
    };
  }, [settings]);

  useEffect(() => {
    api.get<ReferenceStatus>("/api/reference/status").then(setRef).catch(() => undefined);
    api.get<{ fines: Fine[] }>("/api/fines").then((r) => setFines(Object.fromEntries(r.fines.map((f) => [f.id, f])))).catch(() => undefined);
  }, [dataVersion]);

  // ------------------------------------------------------------------ données amendes
  const baseQuery = useMemo(() => filterQuery(filters), [filters]);

  useEffect(() => {
    api.get<Stats>(`/api/stats${qs(baseQuery)}`).then((s) => {
      const ms = (s.time.months ?? []).map((m) => m.month);
      setMonths(ms);
      setMonthIdx(ms.length ? ms.length - 1 : 0);
    }).catch(() => undefined);
  }, [baseQuery, dataVersion]);

  const layerQuery = useMemo(() => {
    if (mode !== "time" || !months.length) return baseQuery;
    const ym = months[Math.min(monthIdx, months.length - 1)];
    const [a, b] = monthBounds(ym);
    return { ...baseQuery, date_from: cumulative ? baseQuery.date_from ?? "" : a, date_to: b };
  }, [baseQuery, mode, months, monthIdx, cumulative]);

  useEffect(() => {
    const t = window.setTimeout(() => {
      api.get<MapLayers>(`/api/map/fines${qs(layerQuery)}`).then(setLayers).catch(() => setLayers(null));
    }, 120);
    return () => window.clearTimeout(t);
  }, [layerQuery, dataVersion]);

  useEffect(() => {
    if (!playing) return;
    const t = window.setInterval(() => {
      setMonthIdx((i) => {
        if (i >= months.length - 1) {
          setPlaying(false);
          return i;
        }
        return i + 1;
      });
    }, 1100);
    return () => window.clearInterval(t);
  }, [playing, months.length]);

  // ------------------------------------------------------------------ synchro couches
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !layers) return;
    (map.getSource("fines-seg") as GeoJSONSource).setData(layers.segments as any);
    (map.getSource("fines-st") as GeoJSONSource).setData(layers.stations as any);
    (map.getSource("fines-od") as GeoJSONSource).setData(layers.od as any);
    (map.getSource("fines-pt") as GeoJSONSource).setData(layers.fines as any);
  }, [layers, ready]);

  const scaleMax = useMemo(() => {
    if (!layers) return 1;
    if (mode === "total") return layers.max.total;
    if (mode === "mean") return layers.max.mean;
    return layers.max.count;
  }, [layers, mode]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    map.setPaintProperty("fines-seg", "line-color", metricColor(mode, scaleMax) as any);
    map.setPaintProperty("fines-seg", "line-width", metricWidth(mode, scaleMax) as any);
    map.setPaintProperty("fines-seg-casing", "line-width", ["+", metricWidth(mode, scaleMax), 3] as any);
    const smax = Math.max(1, layers?.max.station_count ?? 1);
    map.setPaintProperty("fines-st", "circle-radius", ["interpolate", ["linear"], ["get", "count"], 1, 5, Math.max(2, smax), 14] as any);
  }, [mode, scaleMax, ready, layers]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const set = (id: string, on: boolean) => map.getLayer(id) && map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
    set("rail-lines", vis.lines);
    set("rail-branch", vis.lines && infra.raccordement);
    set("rail-routes", vis.routes);
    set("rail-stations", vis.stations);
    set("station-labels", vis.stations);
    set("fines-seg", vis.fines);
    set("fines-seg-casing", vis.fines);
    set("fines-st", vis.fines);
    set("fines-od", vis.fines && vis.od);
    set("fines-pt", vis.fines && vis.points);
    if (!basemapError) set("basemap", vis.basemap);
    set("orm", vis.orm);
    const infraOn = Object.entries(infra).filter(([, v]) => v).map(([k]) => k);
    map.setFilter("rail-lines", ["all", ["!=", ["get", "infra_type"], "raccordement"], ["in", ["get", "infra_type"], ["literal", infraOn]]]);
    const catsOn = Object.entries(cats).filter(([, v]) => v).map(([k]) => k);
    map.setFilter("rail-routes", ["in", ["get", "category"], ["literal", catsOn]]);
    // le réseau de fond s'efface quand les amendes sont affichées
    const fade = vis.fines && (layers?.segments.features.length ?? 0) > 0;
    map.setPaintProperty("rail-lines", "line-opacity", fade ? 0.45 : 0.85);
    map.setPaintProperty("rail-routes", "line-opacity", fade ? 0.35 : 0.85);
  }, [vis, infra, cats, ready, layers, basemapError]);

  // ------------------------------------------------------------------ sélection
  const highlight = useCallback((geom: any | null) => {
    const map = mapRef.current;
    if (!map) return;
    (map.getSource("highlight") as GeoJSONSource | undefined)?.setData(
      geom ? ({ type: "Feature", geometry: geom, properties: {} } as any) : ({ type: "FeatureCollection", features: [] } as any),
    );
  }, []);

  const selectStation = useCallback(async (id: string, name?: string) => {
    setTab("details");
    highlight(null);
    setSel({ kind: "station", title: name ?? id, data: null });
    try {
      const [d, s] = await Promise.all([
        api.get<any>(`/api/reference/stations/${encodeURIComponent(id)}`),
        api.get<Stats>(`/api/stats${qs({ ...baseQuery, station: id })}`),
      ]);
      setSel({ kind: "station", title: d.name, data: d, stats: s });
    } catch {
      setSel({ kind: "station", title: name ?? id, data: { id }, stats: null });
    }
  }, [baseQuery, highlight]);

  const selectLine = useCallback(async (id: string) => {
    setTab("details");
    try {
      const [d, s] = await Promise.all([
        api.get<any>(`/api/reference/lines/${encodeURIComponent(id)}${qs({ geometry: true })}`),
        api.get<Stats>(`/api/stats${qs({ ...baseQuery, line: id })}`),
      ]);
      highlight(d.geometry);
      setSel({ kind: "line", title: d.name || d.code || id, data: d, stats: s });
    } catch {
      setSel({ kind: "line", title: id, data: { id }, stats: null });
    }
  }, [baseQuery, highlight]);

  const selectRoute = useCallback(async (id: string) => {
    setTab("details");
    try {
      const [d, s] = await Promise.all([
        api.get<any>(`/api/reference/routes/${encodeURIComponent(id)}`),
        api.get<Stats>(`/api/stats${qs({ ...baseQuery, route: id })}`),
      ]);
      setSel({ kind: "route", title: [d.category, d.short_name, d.long_name].filter(Boolean).join(" "), data: d, stats: s });
    } catch {
      setSel({ kind: "route", title: id, data: { id }, stats: null });
    }
  }, [baseQuery]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const onClick = (e: maplibregl.MapMouseEvent) => {
      const feats = map.queryRenderedFeatures(e.point, { layers: INTERACTIVE.filter((l) => map.getLayer(l)) });
      if (!feats.length) return;
      const f: MapGeoJSONFeature = feats[0];
      const p: any = f.properties;
      const parse = (v: any) => (typeof v === "string" ? JSON.parse(v) : v);
      switch (f.layer.id) {
        case "fines-pt":
          setTab("details");
          setSel({ kind: "fine", title: `Amende n° ${p.fine_id}`, data: { id: p.fine_id } });
          break;
        case "fines-seg":
          setTab("details");
          highlight(f.geometry);
          setSel({ kind: "segment", title: p.line_name || p.line_code || "Tronçon", data: { ...p, hours: parse(p.hours), types: parse(p.types), months: parse(p.months), fine_ids: parse(p.fine_ids) } });
          break;
        case "fines-st":
          selectStation(p.station_id, p.name);
          break;
        case "fines-od":
          setTab("details");
          setSel({ kind: "od", title: `${p.origin} → ${p.dest}`, data: { ...p, fine_ids: parse(p.fine_ids) } });
          break;
        case "rail-stations":
          selectStation(p.id, p.name);
          break;
        case "rail-routes":
          selectRoute(p.id);
          break;
        default:
          selectLine(p.id);
      }
    };
    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10 });
    const onMove = (e: maplibregl.MapMouseEvent) => {
      const feats = map.queryRenderedFeatures(e.point, { layers: INTERACTIVE.filter((l) => map.getLayer(l)) });
      map.getCanvas().style.cursor = feats.length ? "pointer" : "";
      const f = feats[0];
      if (!f) {
        popup.remove();
        return;
      }
      const p: any = f.properties;
      let html = "";
      if (f.layer.id === "fines-seg") html = `<b>${p.line_name || "Tronçon"}</b><br/>${p.count} amende(s) · ${money(p.total)}${p.mean ? `<br/>moyenne ${money(p.mean)}` : ""}`;
      else if (f.layer.id === "fines-st") html = `<b>${p.name}</b><br/>${p.count} amende(s) · ${money(p.total)}`;
      else if (f.layer.id === "fines-pt") html = `<b>Amende du ${date(p.date)}</b>${p.time ? ` à ${p.time}` : ""}<br/>${money(p.amount)}`;
      else if (f.layer.id === "fines-od") html = `<b>${p.origin} → ${p.dest}</b><br/>relation sans tracé ferroviaire<br/>${p.count} amende(s)`;
      else if (f.layer.id === "rail-stations") html = `<b>${p.name}</b>${p.uic ? `<br/>UIC ${p.uic}` : ""}`;
      else if (f.layer.id === "rail-routes") html = `<b>${p.short_name || ""} ${p.long_name || ""}</b><br/>${label(options?.train_types, p.category)} (itinéraire commercial)`;
      else html = `<b>${p.name || p.code || "Ligne"}</b><br/>${label(options?.infra_types, p.infra_type)} (ligne physique)`;
      popup.setLngLat(e.lngLat).setHTML(html).addTo(map);
    };
    const onLeave = () => popup.remove();
    map.on("click", onClick);
    map.on("mousemove", onMove);
    map.getCanvas().addEventListener("mouseleave", onLeave);
    return () => {
      map.off("click", onClick);
      map.off("mousemove", onMove);
      map.getCanvas().removeEventListener("mouseleave", onLeave);
      popup.remove();
    };
  }, [ready, selectLine, selectRoute, selectStation, highlight, options]);

  // lien direct ?station=... ou ?line=...
  useEffect(() => {
    if (!ready) return;
    const st = params.get("station");
    const ln = params.get("line");
    if (st) selectStation(st);
    else if (ln) selectLine(ln);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  // ------------------------------------------------------------------ itinéraire
  const computePath = async () => {
    setPathErr(null);
    setPathRes(null);
    if (!from || !to) return;
    try {
      const r = await api.get<any>(`/api/reference/path${qs({ from: from.id, to: to.id, via: via?.id })}`);
      setPathRes(r);
      const map = mapRef.current;
      if (map) {
        (map.getSource("path") as GeoJSONSource).setData(r);
        const cs: number[][] = r.geometry.coordinates;
        const b = cs.reduce((acc, c) => acc.extend(c as [number, number]), new maplibregl.LngLatBounds(cs[0] as [number, number], cs[0] as [number, number]));
        map.fitBounds(b, { padding: 60, duration: 600 });
      }
    } catch (e: any) {
      setPathErr(e.message);
    }
  };
  const clearPath = () => {
    setPathRes(null);
    (mapRef.current?.getSource("path") as GeoJSONSource | undefined)?.setData({ type: "FeatureCollection", features: [] } as any);
  };

  const flyTo = (s: StationCandidate) => {
    mapRef.current?.flyTo({ center: [s.lon, s.lat], zoom: Math.max(mapRef.current.getZoom(), 11), duration: 900 });
    selectStation(s.id, s.name);
  };

  const noRoutes = (ref?.counts.routes ?? 0) === 0;
  const lineSources = ref?.counts.line_sources ?? [];
  const onlyFallback = lineSources.length > 0 && lineSources.filter((l) => l.active).every((l) => l.source === "naturalearth_rail");

  return (
    <div className="map-page">
      <div className="map-wrap" ref={wrap}>
        <div className="map" ref={container} aria-label="Carte ferroviaire France - Belgique" />
        <div className="map-search">
          <StationPicker placeholder="Rechercher une gare (FR / NL)" onSelect={(s) => s && flyTo(s)} />
        </div>
        {basemapError && <div className="map-toast">Fond de carte en ligne indisponible : fond hors ligne utilisé</div>}
        <Legend mode={mode} max={scaleMax} layers={layers} vis={vis} noRoutes={noRoutes} options={options} />
      </div>
      <aside className="map-side">
        <div className="tabs" role="tablist">
          {(["fines", "layers", "details", "route"] as Tab[]).map((t) => (
            <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)} role="tab" aria-selected={tab === t}>
              {t === "fines" ? "Amendes" : t === "layers" ? "Couches" : t === "details" ? "Détails" : "Itinéraire"}
            </button>
          ))}
        </div>
        <div className="side-body">
          {tab === "fines" && (
            <>
              {onlyFallback && (
                <div className="notice warn small">
                  Réseau affiché : Natural Earth (généralisé, sans nom de ligne). Importez les données SNCF Réseau / Infrabel dans
                  <Link to="/parametres"> Paramètres</Link> pour des lignes précises et nommées.
                </div>
              )}
              <div>
                <div className="small secondary" style={{ marginBottom: 6 }}>Mode d'affichage</div>
                <div className="seg" style={{ flexWrap: "wrap" }}>
                  {MODES.map((m) => (
                    <button key={m.id} className={mode === m.id ? "on" : ""} onClick={() => setMode(m.id)}>{m.label}</button>
                  ))}
                </div>
              </div>
              {mode === "time" && months.length > 0 && (
                <div className="card" style={{ padding: 12 }}>
                  <div className="row">
                    <button className="btn sm" onClick={() => { if (monthIdx >= months.length - 1) setMonthIdx(0); setPlaying((p) => !p); }}>
                      {playing ? "Pause" : "Lecture"}
                    </button>
                    <b>{monthLabel(months[Math.min(monthIdx, months.length - 1)])}</b>
                    <span className="grow" />
                    <label className="check small"><input type="checkbox" checked={cumulative} onChange={(e) => setCumulative(e.target.checked)} /> cumulé</label>
                  </div>
                  <input type="range" min={0} max={months.length - 1} value={monthIdx} onChange={(e) => setMonthIdx(Number(e.target.value))} style={{ width: "100%", marginTop: 8 }} aria-label="Mois" />
                  <div className="legend-scale small"><span>{monthLabel(months[0])}</span><span>{monthLabel(months[months.length - 1])}</span></div>
                </div>
              )}
              <FiltersBar value={filters} onChange={setFilters} compact />
              {layers && (
                <div className="grid grid-2">
                  <div className="card kpi" style={{ padding: 12 }}>
                    <div className="kpi-label">Amendes affichées</div>
                    <div className="kpi-value" style={{ fontSize: 22 }}>{number(layers.count)}</div>
                  </div>
                  <div className="card kpi" style={{ padding: 12 }}>
                    <div className="kpi-label">Non géolocalisées</div>
                    <div className="kpi-value" style={{ fontSize: 22 }}>{number(layers.unlocated)}</div>
                    <div className="kpi-sub">comptées dans les statistiques</div>
                  </div>
                </div>
              )}
              <TopSegments layers={layers} onPick={(f) => {
                const map = mapRef.current;
                const cs: number[][] = f.geometry.coordinates;
                if (map && cs.length) map.fitBounds(cs.reduce((b, c) => b.extend(c as [number, number]), new maplibregl.LngLatBounds(cs[0] as [number, number], cs[0] as [number, number])), { padding: 80, maxZoom: 11 });
                highlight(f.geometry);
                setTab("details");
                const p = f.properties;
                setSel({ kind: "segment", title: p.line_name || p.line_code || "Tronçon", data: p });
              }} mode={mode} />
              <p className="muted small">
                Les tronçons colorés correspondent aux trajets reliés aux amendes (confirmés par numéro de train, ou présumés par plus court chemin).
                Les relations en pointillé n'ont pas de tracé ferroviaire calculable : elles ne représentent pas une voie.
              </p>
            </>
          )}
          {tab === "layers" && (
            <LayersPanel vis={vis} setVis={setVis} infra={infra} setInfra={setInfra} cats={cats} setCats={setCats}
              noRoutes={noRoutes} options={options} settingsOrm={!!settings?.openrailwaymap_overlay} online={!!settings?.online_basemap} refStatus={ref} />
          )}
          {tab === "details" && <Details sel={sel} fines={fines} options={options} onStation={selectStation} onLine={selectLine} onRoute={selectRoute}
            onRouteFrom={(s) => { setFrom(s); setTab("route"); }} onRouteTo={(s) => { setTo(s); setTab("route"); }} />}
          {tab === "route" && (
            <div className="stack">
              <p className="secondary small">
                Calcule le plus court chemin entre deux gares sur le réseau physique importé. C'est une hypothèse de parcours sur l'infrastructure :
                elle ne correspond pas forcément au trajet d'un train commercial ni à un horaire.
              </p>
              <label className="field">Départ<StationPicker value={from ? { id: from.id, name: from.name } : null} onSelect={setFrom} /></label>
              <label className="field">Via (facultatif)<StationPicker value={via ? { id: via.id, name: via.name } : null} onSelect={setVia} /></label>
              <label className="field">Arrivée<StationPicker value={to ? { id: to.id, name: to.name } : null} onSelect={setTo} /></label>
              <div className="row">
                <button className="btn primary" disabled={!from || !to} onClick={computePath}>Calculer</button>
                {pathRes && <button className="btn ghost" onClick={clearPath}>Effacer</button>}
              </div>
              {pathErr && <div className="notice bad">{pathErr}</div>}
              {pathRes && (
                <div className="card">
                  <div className="kpi"><div className="kpi-label">Distance sur le réseau</div><div className="kpi-value">{number(pathRes.properties.length_km)} km</div></div>
                  <div className="sep" />
                  <h3>Lignes physiques empruntées</h3>
                  <table>
                    <tbody>
                      {pathRes.properties.lines.map((l: any) => (
                        <tr key={l.id} className="clickable" onClick={() => selectLine(l.id)}>
                          <td>{l.name || l.code || l.id}</td>
                          <td className="num">{number(l.km)} km</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="muted small" style={{ marginTop: 8 }}>{pathRes.properties.disclaimer}</p>
                </div>
              )}
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

// ---------------------------------------------------------------------- légende
function Legend({ mode, max, layers, vis, noRoutes, options }: { mode: Mode; max: number; layers: MapLayers | null; vis: any; noRoutes: boolean; options: any }) {
  const [open, setOpen] = useState(() => window.innerWidth > 900);
  if (!open) return <button className="btn sm legend-toggle" onClick={() => setOpen(true)}>Légende</button>;
  const hasFines = vis.fines && (layers?.segments.features.length ?? 0) + (layers?.stations.features.length ?? 0) > 0;
  const fmt = (v: number) => (mode === "total" || mode === "mean" ? money(v) : number(v));
  return (
    <div className="map-legend">
      <button className="btn ghost sm" style={{ float: "right", padding: "0 6px", marginTop: -4 }} onClick={() => setOpen(false)} aria-label="Masquer la légende">×</button>
      {hasFines && (
        <>
          <h4>
            Amendes par tronçon :{" "}
            {mode === "count" ? "nombre" : mode === "total" ? "montant total" : mode === "mean" ? "montant moyen" : mode === "slot" ? "créneau horaire dominant" : "nombre (période choisie)"}
          </h4>
          {mode === "slot" ? (
            Object.entries(SLOT_COLORS).map(([k, c]) => (
              <div className="legend-row" key={k}><span className="legend-line" style={{ borderColor: c }} />{k}</div>
            ))
          ) : (
            <>
              <div className="legend-ramp" style={{ background: `linear-gradient(90deg, ${SEQUENTIAL.join(",")})` }} />
              <div className="legend-scale"><span>{fmt(0)}</span><span>{fmt(max)}</span></div>
              <div className="muted" style={{ marginTop: 2 }}>couleur et épaisseur proportionnelles</div>
            </>
          )}
          <div className="legend-row"><span className="legend-line" style={{ borderColor: "#c3c2b7", borderTopStyle: "dashed" }} />relation O-D sans tracé</div>
          <div className="legend-row"><span className="swatch" style={{ background: SEQUENTIAL[3], borderRadius: "50%" }} />gare concernée (taille = nombre)</div>
          <div className="sep" style={{ margin: "8px 0" }} />
        </>
      )}
      <h4>Réseau</h4>
      {vis.lines && (
        <>
          <div className="legend-row"><span className="legend-line" style={{ borderColor: INFRA_COLORS.lgv }} />{label(options?.infra_types, "lgv")}</div>
          <div className="legend-row"><span className="legend-line" style={{ borderColor: INFRA_COLORS.classique }} />{label(options?.infra_types, "classique")}</div>
          <div className="legend-row"><span className="legend-line" style={{ borderColor: INFRA_COLORS.inconnu }} />{label(options?.infra_types, "inconnu")}</div>
        </>
      )}
      {vis.routes && !noRoutes && (
        <div className="row" style={{ gap: 8, marginTop: 4 }}>
          {TRAIN_TYPE_ORDER.slice(0, 7).map((c) => (
            <span key={c} className="legend-row" style={{ margin: 0 }}><span className="swatch" style={{ background: TRAIN_TYPE_COLORS[c] }} />{label(options?.train_types, c).split(" (")[0]}</span>
          ))}
        </div>
      )}
      <div className="legend-row"><span className="swatch" style={{ background: "#d9d7d2", borderRadius: "50%" }} />gare</div>
    </div>
  );
}

// ---------------------------------------------------------------------- panneaux
function LayersPanel({ vis, setVis, infra, setInfra, cats, setCats, noRoutes, options, settingsOrm, online, refStatus }: any) {
  const tog = (k: string) => setVis((v: any) => ({ ...v, [k]: !v[k] }));
  return (
    <div className="stack">
      <div className="layer-group">
        <h3>Fond de carte</h3>
        {online && <label className="check"><input type="checkbox" checked={vis.basemap} onChange={() => tog("basemap")} />Fond CARTO sombre (en ligne)</label>}
        {settingsOrm && <label className="check"><input type="checkbox" checked={vis.orm} onChange={() => tog("orm")} />OpenRailwayMap (infrastructure détaillée)</label>}
        {!settingsOrm && <p className="muted small">L'infrastructure détaillée OpenRailwayMap peut être activée dans Paramètres.</p>}
      </div>
      <div className="layer-group">
        <h3>Lignes physiques (infrastructure)</h3>
        <label className="check"><input type="checkbox" checked={vis.lines} onChange={() => tog("lines")} />Afficher le réseau</label>
        {Object.keys(infra).map((k) => (
          <label key={k} className="check" style={{ paddingLeft: 18 }}>
            <input type="checkbox" checked={infra[k]} onChange={() => setInfra({ ...infra, [k]: !infra[k] })} />
            <span className="legend-line" style={{ borderColor: INFRA_COLORS[k] }} />{label(options?.infra_types, k)}
          </label>
        ))}
      </div>
      <div className="layer-group">
        <h3>Itinéraires commerciaux</h3>
        <label className="check"><input type="checkbox" checked={vis.routes} onChange={() => tog("routes")} />Afficher les itinéraires</label>
        {TRAIN_TYPE_ORDER.map((c) => (
          <label key={c} className="check" style={{ paddingLeft: 18 }}>
            <input type="checkbox" checked={cats[c]} onChange={() => setCats({ ...cats, [c]: !cats[c] })} />
            <span className="swatch" style={{ background: TRAIN_TYPE_COLORS[c] }} />{label(options?.train_types, c)}
          </label>
        ))}
        {noRoutes && <div className="notice warn small">Aucun itinéraire commercial importé. Les catégories TER / TGV / Intercités / Transilien / RER / SNCB proviennent des horaires GTFS ou d'OpenStreetMap : importez-les dans Paramètres.</div>}
      </div>
      <div className="layer-group">
        <h3>Gares et amendes</h3>
        <label className="check"><input type="checkbox" checked={vis.stations} onChange={() => tog("stations")} />Gares</label>
        <label className="check"><input type="checkbox" checked={vis.fines} onChange={() => tog("fines")} />Amendes (tronçons et gares)</label>
        <label className="check" style={{ paddingLeft: 18 }}><input type="checkbox" checked={vis.points} onChange={() => tog("points")} />Points d'amende (zoom ≥ 7)</label>
        <label className="check" style={{ paddingLeft: 18 }}><input type="checkbox" checked={vis.od} onChange={() => tog("od")} />Relations O-D sans tracé</label>
      </div>
      {refStatus && (
        <p className="muted small">
          Référentiel : {number(refStatus.counts.stations)} gares, {number(refStatus.counts.active_lines)} lignes actives, {number(refStatus.counts.routes)} itinéraires, {number(refStatus.counts.trains)} numéros de train.
        </p>
      )}
    </div>
  );
}

function TopSegments({ layers, onPick, mode }: { layers: MapLayers | null; onPick: (f: any) => void; mode: Mode }) {
  if (!layers || !layers.segments.features.length) return <div className="empty">Aucun tronçon relié à une amende pour ces filtres.</div>;
  const key = mode === "total" ? "total" : mode === "mean" ? "mean" : "count";
  // regroupe les tronçons par ligne physique pour le classement
  const byLine = new Map<string, any>();
  for (const f of layers.segments.features) {
    const p = f.properties;
    const k = p.line_id;
    const cur = byLine.get(k);
    if (!cur || (p[key] ?? 0) > (cur.properties[key] ?? 0)) byLine.set(k, f);
  }
  const top = [...byLine.values()].sort((a, b) => (b.properties[key] ?? 0) - (a.properties[key] ?? 0)).slice(0, 8);
  return (
    <div className="card" style={{ padding: 12 }}>
      <h3 style={{ marginBottom: 8 }}>Tronçons les plus concernés</h3>
      <div className="rank">
        {top.map((f, i) => (
          <div key={f.properties.edge} className="rank-row" style={{ cursor: "pointer" }} onClick={() => onPick(f)}>
            <span className="pos">{i + 1}</span>
            <div className="lab"><div className="name">{f.properties.line_name || f.properties.line_code || f.properties.line_id}</div></div>
            <div className="vals">
              <div className="main-v">{key === "count" ? number(f.properties.count) : money(f.properties[key])}</div>
              <div className="sub-v">{key === "count" ? money(f.properties.total) : `${f.properties.count} amende(s)`}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function FineList({ ids, fines, options }: { ids: number[]; fines: Record<number, Fine>; options: any }) {
  const list = ids.map((i) => fines[i]).filter(Boolean);
  if (!list.length) return null;
  return (
    <div className="table-wrap">
      <table>
        <thead><tr><th>Date</th><th>Trajet</th><th className="num">Montant</th><th /></tr></thead>
        <tbody>
          {list.map((f) => (
            <tr key={f.id}>
              <td className="nowrap">{date(f.fine_date)}<div className="muted small">{f.fine_time ?? ""}</div></td>
              <td>{f.origin_name ?? "?"} → {f.dest_name ?? "?"}<div className="muted small">{label(options?.train_types, f.train_type)} {f.train_number ?? ""}{f.is_demo ? " · exemple" : ""}</div></td>
              <td className="num">{money(f.amount_initial)}</td>
              <td className="nowrap">
                <Link to={`/amendes?id=${f.id}`} className="small">fiche</Link>
                {f.document_id && <> · <a className="small" href={`/api/documents/${f.document_id}/file`} target="_blank" rel="noreferrer">document</a></>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StatsSummary({ stats }: { stats?: Stats | null }) {
  if (!stats) return null;
  if (stats.empty) return <p className="muted small">Aucune amende associée (avec les filtres actuels).</p>;
  const s = stats.summary;
  const hours = stats.time.hours ?? [];
  return (
    <div className="stack">
      <div className="grid grid-3">
        <div className="kpi"><div className="kpi-label">Amendes</div><div className="kpi-value" style={{ fontSize: 20 }}>{number(s.count)}</div></div>
        <div className="kpi"><div className="kpi-label">Montant total</div><div className="kpi-value" style={{ fontSize: 20 }}>{money(s.total)}</div></div>
        <div className="kpi"><div className="kpi-label">Moyenne</div><div className="kpi-value" style={{ fontSize: 20 }}>{money(s.mean)}</div></div>
      </div>
      {hours.some((h) => h.count) && (
        <div>
          <div className="small secondary">Répartition horaire</div>
          <Chart className="" option={columnChart(hours.map((h) => `${h.hour}h`), hours, "count")} ariaLabel="Amendes par heure" />
        </div>
      )}
      {(stats.rankings.train_types?.by_count ?? []).length > 0 && (
        <div className="small secondary">Types de trains : {stats.rankings.train_types.by_count.map((t) => `${t.label} (${t.count})`).join(", ")}</div>
      )}
    </div>
  );
}

function Details({ sel, fines, options, onStation, onLine, onRoute, onRouteFrom, onRouteTo }: {
  sel: Selection | null; fines: Record<number, Fine>; options: any;
  onStation: (id: string, name?: string) => void; onLine: (id: string) => void; onRoute: (id: string) => void;
  onRouteFrom: (s: StationCandidate) => void; onRouteTo: (s: StationCandidate) => void;
}) {
  if (!sel) return <div className="empty">Cliquez sur une gare, une ligne, un tronçon coloré ou une amende sur la carte.</div>;
  const d = sel.data ?? {};
  const kindLabel = { station: "Gare", line: "Ligne physique", route: "Itinéraire commercial", segment: "Tronçon (amendes)", fine: "Amende", od: "Relation origine-destination" }[sel.kind];
  return (
    <div className="stack">
      <div>
        <div className="muted small">{kindLabel}</div>
        <h2>{sel.title}</h2>
      </div>
      {sel.kind === "station" && d.id && (
        <>
          <div className="small secondary">
            {d.uic && <>UIC {d.uic} · </>}{d.country ?? ""} · source : {d.sources ?? d.source}
            {d.on_network === false && <div className="badge warn" style={{ marginTop: 6 }}>non rattachée au réseau importé</div>}
          </div>
          {d.names?.length > 1 && <div className="small muted">Autres noms : {d.names.map((n: any) => n.name).filter((n: string) => n !== d.name).slice(0, 6).join(", ")}</div>}
          <div className="row">
            <button className="btn sm" onClick={() => onRouteFrom({ id: d.id, name: d.name } as StationCandidate)}>Itinéraire depuis</button>
            <button className="btn sm" onClick={() => onRouteTo({ id: d.id, name: d.name } as StationCandidate)}>Itinéraire vers</button>
          </div>
          {d.routes?.length > 0 && (
            <div className="small">
              <div className="secondary">Itinéraires desservant la gare :</div>
              {d.routes.slice(0, 12).map((r: any) => (
                <a key={r.id} onClick={() => onRoute(r.id)} style={{ cursor: "pointer", marginRight: 8 }}>{r.category} {r.short_name ?? r.long_name}</a>
              ))}
            </div>
          )}
          <StatsSummary stats={sel.stats} />
          <FineList ids={(sel.stats?.empty ? [] : undefined) ?? Object.values(fines).filter((f) => [f.origin_resolved_id, f.dest_resolved_id, f.control_resolved_id].includes(d.id)).map((f) => f.id)} fines={fines} options={options} />
        </>
      )}
      {sel.kind === "line" && (
        <>
          <div className="small secondary">
            {d.code && <>Code {d.code} · </>}{label(options?.infra_types, d.infra_type)} · {d.country ?? ""} · {number(d.length_km)} km
            {d.status && <> · statut : {d.status}</>}
            <div className="muted">Source : {d.source}{d.electrified ? ` · électrification : ${d.electrified}` : ""}</div>
          </div>
          <p className="muted small">Une ligne physique est une infrastructure : plusieurs itinéraires commerciaux peuvent l'emprunter.</p>
          <StatsSummary stats={sel.stats} />
          <FineList ids={Object.values(fines).filter((f) => f.links.some((l) => l.kind === "line" && l.ref_id === d.id)).map((f) => f.id)} fines={fines} options={options} />
        </>
      )}
      {sel.kind === "route" && (
        <>
          <div className="small secondary">{d.operator ?? ""} · source : {d.source}</div>
          {d.stops?.length > 0 && (
            <div className="small">
              <div className="secondary">Arrêts (desserte la plus fréquente) :</div>
              {d.stops.map((s: any, i: number) => (
                <span key={s.seq}>{i > 0 && " · "}<a style={{ cursor: "pointer" }} onClick={() => onStation(s.id, s.name)}>{s.name}</a></span>
              ))}
            </div>
          )}
          {d.trains?.length > 0 && <div className="small muted">Numéros de train : {d.trains.slice(0, 30).join(", ")}{d.trains.length > 30 ? "..." : ""}</div>}
          <StatsSummary stats={sel.stats} />
        </>
      )}
      {sel.kind === "segment" && (
        <>
          <div className="grid grid-3">
            <div className="kpi"><div className="kpi-label">Amendes</div><div className="kpi-value" style={{ fontSize: 20 }}>{number(d.count)}</div></div>
            <div className="kpi"><div className="kpi-label">Montant total</div><div className="kpi-value" style={{ fontSize: 20 }}>{money(d.total)}</div></div>
            <div className="kpi"><div className="kpi-label">Moyenne</div><div className="kpi-value" style={{ fontSize: 20 }}>{money(d.mean)}</div></div>
          </div>
          <div className="small secondary">
            {number(d.confirmed)} trajet(s) confirmé(s), {number(d.presumed)} présumé(s) · tronçon de {number(d.length_km)} km
            {d.dominant_slot && <> · créneau dominant : {d.dominant_slot}</>}
          </div>
          {d.types && <div className="small secondary">Types de trains : {Object.entries(d.types).map(([k, v]) => `${label(options?.train_types, k)} (${v})`).join(", ")}</div>}
          {Array.isArray(d.hours) && (
            <Chart option={columnChart(d.hours.map((_: number, h: number) => `${h}h`), d.hours.map((c: number) => ({ count: c, total: 0, mean: null })), "count")} ariaLabel="Répartition horaire du tronçon" />
          )}
          <button className="btn sm" onClick={() => onLine(d.line_id)}>Voir la ligne physique complète</button>
          <FineList ids={d.fine_ids ?? []} fines={fines} options={options} />
        </>
      )}
      {sel.kind === "od" && (
        <>
          <div className="notice warn small">Les gares sont identifiées mais aucun tracé ferroviaire n'a pu être calculé sur le réseau importé : la ligne en pointillé n'est pas une voie.</div>
          <FineList ids={d.fine_ids ?? []} fines={fines} options={options} />
        </>
      )}
      {sel.kind === "fine" && <FineDetail fine={fines[d.id]} options={options} onStation={onStation} onLine={onLine} />}
    </div>
  );
}

function FineDetail({ fine, options, onStation, onLine }: { fine?: Fine; options: any; onStation: (id: string, n?: string) => void; onLine: (id: string) => void }) {
  if (!fine) return <div className="empty">Amende introuvable.</div>;
  const geo = fine.geo_detail ?? {};
  return (
    <div className="stack">
      {fine.is_demo ? <span className="badge demo">Exemple fictif</span> : null}
      <table>
        <tbody>
          <tr><td className="muted">Date</td><td>{date(fine.fine_date)} {fine.fine_time ?? ""}</td></tr>
          <tr><td className="muted">Montant</td><td>{money(fine.amount_initial)}{fine.amount_paid !== null && <> · payé {money(fine.amount_paid)}</>}</td></tr>
          <tr><td className="muted">Trajet</td><td>
            {fine.origin_resolved_id ? <a style={{ cursor: "pointer" }} onClick={() => onStation(fine.origin_resolved_id!)}>{geo.origin?.name ?? fine.origin_name}</a> : fine.origin_name ?? "?"}
            {" → "}
            {fine.dest_resolved_id ? <a style={{ cursor: "pointer" }} onClick={() => onStation(fine.dest_resolved_id!)}>{geo.dest?.name ?? fine.dest_name}</a> : fine.dest_name ?? "?"}
          </td></tr>
          <tr><td className="muted">Train</td><td>{label(options?.train_types, fine.train_type)} {fine.train_number ?? ""} {fine.line_label ?? ""}</td></tr>
          <tr><td className="muted">Motif</td><td>{label(options?.reasons, fine.reason)}</td></tr>
          <tr><td className="muted">Statut</td><td>{label(options?.statuses, fine.status)}</td></tr>
          <tr><td className="muted">Localisation</td><td><span className="badge"><span className="dot" style={{ background: GEO_COLORS[fine.geo_status] }} />{label(options?.geo_statuses, fine.geo_status)}</span></td></tr>
        </tbody>
      </table>
      {fine.links.filter((l) => l.kind === "line").length > 0 && (
        <div className="small">
          <div className="secondary">Lignes physiques{fine.geo_status === "path_inferred" ? " (présumées)" : ""} :</div>
          {fine.links.filter((l) => l.kind === "line").map((l) => (
            <div key={l.ref_id}><a style={{ cursor: "pointer" }} onClick={() => onLine(l.ref_id)}>{l.label}</a> <span className="muted">{number(l.km)} km</span></div>
          ))}
        </div>
      )}
      <div className="row">
        <Link className="btn sm" to={`/amendes?id=${fine.id}`}>Modifier / valider</Link>
        {fine.document_id && <a className="btn sm" href={`/api/documents/${fine.document_id}/file`} target="_blank" rel="noreferrer">Ouvrir le document source</a>}
      </div>
    </div>
  );
}
