import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, qs } from "../api";
import { label, useApp } from "../components/AppContext";
import Chart from "../components/Chart";
import { columnChart, heatmapChart, monthsChart, type Metric } from "../components/charts";
import FiltersBar, { filterQuery } from "../components/FiltersBar";
import RankingCard, { MetricSwitch } from "../components/Ranking";
import { money, number } from "../format";
import { SERIES } from "../theme";
import type { FilterState, Stats } from "../types";

export function Kpis({ s }: { s: Stats["summary"] }) {
  return (
    <div className="grid grid-kpi">
      <div className="card kpi"><div className="kpi-label">Nombre d'amendes</div><div className="kpi-value">{number(s.count)}</div><div className="kpi-sub">{s.first_date ? `du ${s.first_date.split("-").reverse().join("/")} au ${s.last_date?.split("-").reverse().join("/")}` : "—"}</div></div>
      <div className="card kpi"><div className="kpi-label">Montant total des amendes</div><div className="kpi-value">{money(s.total)}</div><div className="kpi-sub">{s.with_amount !== undefined && s.with_amount < s.count ? `${s.count - s.with_amount} sans montant connu` : "montants initiaux"}</div></div>
      <div className="card kpi"><div className="kpi-label">Montant total payé</div><div className="kpi-value">{money(s.paid)}</div><div className="kpi-sub">{s.with_paid_amount ?? 0} amende(s) avec montant payé connu</div></div>
      <div className="card kpi"><div className="kpi-label">Montant moyen</div><div className="kpi-value">{money(s.mean)}</div><div className="kpi-sub">min {money(s.min)} · max {money(s.max)}</div></div>
      <div className="card kpi"><div className="kpi-label">Montant médian</div><div className="kpi-value">{money(s.median)}</div><div className="kpi-sub">moins sensible aux montants extrêmes</div></div>
    </div>
  );
}

export function Caveats({ items, summary }: { items: string[]; summary?: Stats["summary"] }) {
  return (
    <div className="notice">
      <b>Lecture des chiffres</b>
      <ul>
        {items.map((c, i) => <li key={i}>{c}</li>)}
        {summary && (summary.not_geolocated ?? 0) > 0 && <li>{summary.not_geolocated} amende(s) non géolocalisée(s) : incluses dans les totaux, absentes des classements par ligne.</li>}
      </ul>
    </div>
  );
}

export default function StatsPage() {
  const { options, dataVersion } = useApp();
  const navigate = useNavigate();
  const [filters, setFilters] = useState<FilterState>({});
  const [stats, setStats] = useState<Stats | null>(null);
  const [lineOpts, setLineOpts] = useState<{ key: string; label: string }[]>([]);
  const [routeOpts, setRouteOpts] = useState<{ key: string; label: string }[]>([]);
  const [hourMetric, setHourMetric] = useState<Metric>("count");
  const [monthMetric, setMonthMetric] = useState<Metric>("count");
  const [dayMetric, setDayMetric] = useState<Metric>("count");
  const query = useMemo(() => filterQuery(filters), [filters]);

  useEffect(() => {
    api.get<Stats>(`/api/stats${qs(query)}`).then(setStats).catch(() => setStats(null));
  }, [query, dataVersion]);
  // listes de lignes disponibles (sur l'ensemble, sans filtre)
  useEffect(() => {
    api.get<Stats>("/api/stats").then((s) => {
      setLineOpts((s.rankings.lines?.by_count ?? []).map((l) => ({ key: l.key, label: l.label })));
      setRouteOpts((s.rankings.routes?.by_count ?? []).map((l) => ({ key: l.key, label: l.label })));
    }).catch(() => undefined);
  }, [dataVersion]);

  const t = stats?.time ?? {};
  const weekdays = options?.weekdays ?? ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"];
  const r = stats?.rankings ?? {};
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Statistiques</h1>
          <p>Nombre, montant total et montant moyen de vos amendes, par ligne, train, gare, horaire et période.</p>
        </div>
        <div className="row">
          <a className="btn" href={`/api/export/stats.csv${qs(query)}`}>Statistiques CSV</a>
          <a className="btn" href={`/api/export/stats.json${qs(query)}`}>Statistiques JSON</a>
          <a className="btn" href={`/api/export/fines.csv${qs(query)}`}>Amendes filtrées CSV</a>
        </div>
      </div>
      <div className="card" style={{ marginBottom: 14 }}>
        <FiltersBar value={filters} onChange={setFilters} facets={stats?.facets} lines={lineOpts} routes={routeOpts} />
      </div>
      {!stats ? (
        <div className="empty">Chargement...</div>
      ) : stats.empty ? (
        <div className="empty">Aucune amende ne correspond à ces filtres.</div>
      ) : (
        <div className="stack" style={{ gap: 14 }}>
          <Kpis s={stats.summary} />
          <Caveats items={stats.caveats} summary={stats.summary} />
          <div className="grid grid-2">
            <RankingCard title="Lignes physiques" subtitle="Infrastructure empruntée par les trajets reliés aux amendes" ranking={r.lines}
              onPick={(i) => navigate(`/carte?line=${encodeURIComponent(i.key)}`)} emptyText="Aucune amende reliée à une ligne physique." />
            <RankingCard title="Lignes commerciales / itinéraires" subtitle="Itinéraire du train ou ligne indiquée sur le document" ranking={r.routes}
              onPick={(i) => setFilters({ ...filters, route: i.key })} emptyText="Aucune ligne commerciale identifiée (importez le GTFS ou renseignez la ligne)." />
            <RankingCard title="Trains (numéros)" ranking={r.trains} onPick={(i) => setFilters({ ...filters, train_number: i.key })} />
            <RankingCard title="Catégories de trains" ranking={r.train_types} />
            <RankingCard title="Relations origine → destination" ranking={r.od} />
            <RankingCard title="Gares (départ, arrivée ou contrôle)" ranking={r.stations}
              onPick={(i) => setFilters({ ...filters, station: i.key, station_name: i.label })} />
            <RankingCard title="Gares de départ" ranking={r.origins} />
            <RankingCard title="Gares d'arrivée" ranking={r.destinations} />
          </div>
          <div className="card">
            <div className="card-head">
              <div><h2>Évolution mensuelle</h2><p>{monthMetric === "count" ? "Nombre d'amendes" : monthMetric === "total" ? "Montant total" : "Montant moyen"} par mois</p></div>
              <MetricSwitch value={monthMetric} onChange={setMonthMetric} />
            </div>
            <Chart className="tall" option={monthsChart(t.months ?? [], monthMetric)} ariaLabel="Évolution mensuelle" />
          </div>
          <div className="grid grid-2">
            <div className="card">
              <div className="card-head">
                <div><h2>Heures</h2><p>Heure du contrôle (si connue)</p></div>
                <MetricSwitch value={hourMetric} onChange={setHourMetric} />
              </div>
              <Chart option={columnChart((t.hours ?? []).map((h) => `${h.hour}h`), t.hours ?? [], hourMetric, SERIES[0], (t.hours ?? []).map((h) => `${h.hour}h - ${h.hour + 1}h`))} ariaLabel="Amendes par heure" />
              {(stats.summary.missing?.time ?? 0) > 0 && <p className="muted small">{stats.summary.missing!.time} amende(s) sans heure connue.</p>}
            </div>
            <div className="card">
              <div className="card-head">
                <div><h2>Jours de la semaine</h2></div>
                <MetricSwitch value={dayMetric} onChange={setDayMetric} />
              </div>
              <Chart option={columnChart((t.weekdays ?? []).map((w) => w.label.slice(0, 3)), t.weekdays ?? [], dayMetric, SERIES[0], (t.weekdays ?? []).map((w) => w.label))} ariaLabel="Amendes par jour" />
            </div>
          </div>
          <div className="grid grid-2">
            <div className="card">
              <div className="card-head"><div><h2>Jour × heure</h2><p>Nombre d'amendes par créneau</p></div></div>
              <Chart className="tall" option={heatmapChart(t.heatmap ?? [], weekdays)} ariaLabel="Carte de chaleur jour et heure" />
            </div>
            <div className="card">
              <div className="card-head"><div><h2>Horaires classés</h2><p>Heures avec le plus d'amendes</p></div></div>
              <table>
                <thead><tr><th>Heure</th><th className="num">Nombre</th><th className="num">Montant total</th><th className="num">Moyenne</th></tr></thead>
                <tbody>
                  {(t.hours_ranked ?? []).slice(0, 10).map((h) => (
                    <tr key={h.hour}><td>{h.hour}h - {h.hour + 1}h</td><td className="num">{h.count}</td><td className="num">{money(h.total)}</td><td className="num">{money(h.mean)}</td></tr>
                  ))}
                </tbody>
              </table>
              <div className="sep" />
              <table>
                <thead><tr><th>Créneau</th><th className="num">Nombre</th><th className="num">Montant total</th></tr></thead>
                <tbody>{(t.slots ?? []).map((s) => <tr key={s.slot}><td>{s.slot}</td><td className="num">{s.count}</td><td className="num">{money(s.total)}</td></tr>)}</tbody>
              </table>
            </div>
          </div>
          <div className="grid grid-3">
            <RankingCard title="Motifs" ranking={r.reasons} limit={9} />
            <RankingCard title="Transporteurs" ranking={r.carriers} limit={8} />
            <RankingCard title="Pays" ranking={r.countries} limit={4} />
          </div>
          <div className="grid grid-2">
            <div className="card">
              <div className="card-head"><h2>Années</h2></div>
              <table>
                <thead><tr><th>Année</th><th className="num">Nombre</th><th className="num">Montant total</th><th className="num">Moyenne</th><th className="num">Payé</th></tr></thead>
                <tbody>{(t.years ?? []).map((y) => <tr key={y.year}><td>{y.year}</td><td className="num">{y.count}</td><td className="num">{money(y.total)}</td><td className="num">{money(y.mean)}</td><td className="num">{money(y.paid)}</td></tr>)}</tbody>
              </table>
            </div>
            <div className="card">
              <div className="card-head"><h2>Qualité des données</h2></div>
              <table>
                <tbody>
                  {Object.entries(stats.summary.by_geo_status ?? {}).map(([k, v]) => <tr key={k}><td>{label(options?.geo_statuses, k)}</td><td className="num">{v}</td></tr>)}
                  <tr><td>Sans montant</td><td className="num">{stats.summary.missing?.amount ?? 0}</td></tr>
                  <tr><td>Sans date</td><td className="num">{stats.summary.missing?.date ?? 0}</td></tr>
                  <tr><td>Sans type de train</td><td className="num">{stats.summary.missing?.train_type ?? 0}</td></tr>
                  {(stats.summary.demo ?? 0) > 0 && <tr><td>Exemples fictifs inclus</td><td className="num">{stats.summary.demo}</td></tr>}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
